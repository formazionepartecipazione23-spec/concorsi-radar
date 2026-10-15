#!/usr/bin/env python3
# =====================================================================
#  Incrocio AUTOMATICO bandi <-> Catalogo formativo (v1 del 15/10/2026)
#  Gira su GitHub Actions nel repo concorsi-radar (vedi incrocio.yml),
#  di norma il lunedi' DOPO il giro settimanale del radar:
#    1. legge l'elenco bandi dal JSON pubblicato su GitHub Pages;
#    2. legge dal database Supabase le materie del 📚 Catalogo formativo
#       e gli incroci gia' presenti (manuali o automatici);
#    3. per ogni bando attivo SENZA incrocio: scarica i PDF (bando e
#       allegati), estrae il testo, isola il programma d'esame e lo
#       incrocia con le materie del catalogo tramite Claude;
#    4. salva l'esito come BOZZA (auto: true) in corsi_altri con
#       tipo='incrocio' e id 'INC-<id bando>'.
#  REGOLA D'ORO: un incrocio gia' esistente NON viene MAI riscritto
#  (ne' manuale ne' automatico): il giro lavora solo sui bandi nuovi.
#  Nel gestionale le bozze compaiono nel dettaglio bando come
#  «bozza automatica»: si confermano (o correggono) col pulsante
#  📚 Copertura catalogo; la conferma toglie il contrassegno di bozza.
#
#  Configurazione SOLO da variabili d'ambiente (mai chiavi nel codice):
#    SUPABASE_URL          es. https://xxxx.supabase.co
#    SUPABASE_SERVICE_KEY  chiave segreta sb_secret_...
#    ANTHROPIC_API_KEY     chiave API Claude (gia' nei secrets del repo)
#    CLAUDE_MODEL          facoltativa (default claude-sonnet-4-5)
#    MAX_BANDI             quanti bandi al massimo in questo giro (default 80)
#    RADAR_URL             facoltativa, URL del JSON del radar
#    RADAR_FILE            facoltativa, percorso locale del JSON (per i test)
#    ANTHROPIC_BASE        facoltativa (per i test)
#    RIFAI                 facoltativa: id di bandi da rianalizzare, separati
#                          da virgola (riscrive anche un incrocio esistente:
#                          usare solo apposta)
# =====================================================================
import os, sys, io, json, re, datetime, time, collections
try:
    from zoneinfo import ZoneInfo
    ROMA = ZoneInfo("Europe/Rome")
except Exception:
    ROMA = None
import requests
from pypdf import PdfReader

RADAR_URL_DEFAULT = "https://formazionepartecipazione23-spec.github.io/concorsi-radar/concorsi_gestionale_latest.json"
UA = {"User-Agent": "FPIncrocio/1.0 (FP Formazione e Partecipazione)"}
MAX_PDF_BYTES   = 25 * 1024 * 1024   # oltre, l'allegato si salta
MAX_FILE_BANDO  = 4                  # quanti file al massimo per bando
MAX_ESTRATTO    = 14000              # caratteri di programma inviati a Claude
MIN_TESTO       = 400                # sotto, il PDF si considera illeggibile

SYSTEM = (
    "Lavori per FP Formazione e Partecipazione (FP CGIL), provider ECM accreditato AGENAS n. 7761. "
    "Rispondi SOLO con un oggetto JSON valido: nessun testo prima o dopo, nessun blocco di codice, "
    "nessun commento. Non inventare dati che non trovi nel testo ricevuto. "
    "Ricevi un JSON con: 'bando' (titolo, ente, profilo, comparto, area, livello, tipo e eventuali "
    "materie indicative di un concorso pubblico), 'programma' (il testo del programma d'esame estratto "
    "dal bando: puo' mancare o essere parziale) e 'materie' (il Catalogo formativo del provider: array "
    "di {id, titolo}). Devi incrociare il concorso con il catalogo per preparare il corso di "
    "preparazione. Restituisci un JSON: {\"materie\": [{\"id\": \"...\", \"motivo\": \"...\"}], "
    "\"mancanti\": [{\"tema\": \"...\", \"motivo\": \"...\"}], \"nota\": \"...\"}. Regole: in 'materie' "
    "metti SOLO id presenti nel catalogo ricevuto (mai inventarne), in ordine di importanza per quel "
    "concorso, con 'motivo' di una frase (perche' serve per quel profilo o dove compare nel programma); "
    "se c'e' il programma d'esame basati PRIMA DI TUTTO su quello, altrimenti deduci le materie tipiche "
    "del profilo da titolo/ente/comparto/area/livello; in 'mancanti' elenca i temi del programma d'esame "
    "che il catalogo NON copre e che andrebbero prodotti (massimo 12, i piu' importanti prima); "
    "'nota' (facoltativa): una sola frase di avvertenza se i dati sono scarsi o il programma manca. "
    "Sii selettivo: solo materie davvero pertinenti, non tutto il catalogo."
)

def env(nome, default=None, obbligatoria=True):
    v = os.environ.get(nome, default)
    if obbligatoria and (v is None or v == ""):
        sys.exit("ERRORE: manca la variabile d'ambiente " + nome)
    return v

BASE  = env("SUPABASE_URL").rstrip("/").removesuffix("/rest/v1")
SKEY  = env("SUPABASE_SERVICE_KEY")
AKEY  = env("ANTHROPIC_API_KEY")
MODEL = os.environ.get("CLAUDE_MODEL") or "claude-sonnet-4-5"
ABASE = (os.environ.get("ANTHROPIC_BASE") or "https://api.anthropic.com").rstrip("/")
MAXB  = int(os.environ.get("MAX_BANDI") or "80")
RIFAI = set(x.strip() for x in (os.environ.get("RIFAI") or "").split(",") if x.strip())

HDR = {"apikey": SKEY, "User-Agent": UA["User-Agent"]}
if SKEY.startswith("eyJ"):
    HDR["Authorization"] = "Bearer " + SKEY

def adesso():
    return datetime.datetime.now(ROMA) if ROMA else datetime.datetime.now()

# ---------------- lettura da Supabase (pagine keyset, come backup_cloud) ----------------
def leggi_tabella(filtro, select="id,data", pagina=200):
    righe, ultimo = [], None
    while True:
        url = BASE + "/rest/v1/corsi_altri?select=" + select + "&" + filtro + "&order=id.asc&limit=" + str(pagina)
        if ultimo is not None:
            url += "&id=gt." + requests.utils.quote(str(ultimo), safe="")
        r = requests.get(url, headers=HDR, timeout=120)
        if r.status_code != 200:
            raise RuntimeError("Supabase (%s): HTTP %d %s" % (filtro, r.status_code, r.text[:200]))
        blocco = r.json()
        righe.extend(blocco)
        if blocco:
            ultimo = blocco[-1]["id"]
        if len(blocco) < pagina:
            return righe

def salva_incrocio(riga):
    r = requests.post(BASE + "/rest/v1/corsi_altri", headers=dict(HDR, **{
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal"}),
        data=json.dumps([riga], ensure_ascii=False).encode("utf-8"), timeout=120)
    if r.status_code not in (200, 201, 204):
        raise RuntimeError("salvataggio %s: HTTP %d %s" % (riga["id"], r.status_code, r.text[:200]))

# ---------------- bandi dal radar ----------------
def leggi_radar():
    f = os.environ.get("RADAR_FILE")
    if f:
        with open(f, encoding="utf-8") as fh:
            return json.load(fh)
    url = os.environ.get("RADAR_URL") or RADAR_URL_DEFAULT
    r = requests.get(url + ("&" if "?" in url else "?") + "t=" + str(int(time.time())),
                     headers=UA, timeout=120)
    if r.status_code != 200:
        raise RuntimeError("radar: HTTP %d da %s" % (r.status_code, url))
    return r.json()

# ---------------- PDF: scarico ed estrazione ----------------
def _urls_bando(b):
    u = b.get("url_allegati")
    urls = (u if isinstance(u, list) else (str(u).split(",") if u else []))
    urls = [str(x).strip() for x in urls if str(x or "").strip()]
    ub = str(b.get("url_bando") or "").strip()
    if ub and ub.lower().endswith(".pdf"):
        urls.append(ub)
    return urls[:MAX_FILE_BANDO]

def testo_pdf(dati):
    try:
        rd = PdfReader(io.BytesIO(dati))
        parti = []
        for pg in rd.pages:
            try:
                parti.append(pg.extract_text() or "")
            except Exception:
                pass
        return "\n".join(parti)
    except Exception:
        return ""

def testo_del_bando(b):
    testo = []
    for url in _urls_bando(b):
        try:
            r = requests.get(url, headers=UA, timeout=90, stream=True)
            if r.status_code != 200:
                continue
            dati = b""
            for pezzo in r.iter_content(262144):
                dati += pezzo
                if len(dati) > MAX_PDF_BYTES:
                    dati = b""
                    break
            if dati[:5] == b"%PDF-":
                t = testo_pdf(dati)
                if t.strip():
                    testo.append(t)
        except Exception:
            continue
    return "\n\n".join(testo)

PAROLE = re.compile(r"programma|prov[ae]\s+(scritt|oral|presel)|materie\s+d.?esame|prova\s+d.?esame|valutazione\s+delle\s+prove", re.I)

def estratto_programma(testo):
    t = re.sub(r"[ \t]+", " ", testo)
    if len(t) <= MAX_ESTRATTO:
        return t
    finestre = []
    for m in PAROLE.finditer(t):
        a, z = max(0, m.start() - 1500), min(len(t), m.end() + 4500)
        if finestre and a <= finestre[-1][1]:
            finestre[-1] = (finestre[-1][0], z)
        else:
            finestre.append((a, z))
    if finestre:
        out = "\n[...]\n".join(t[a:z] for a, z in finestre)
        return out[:MAX_ESTRATTO]
    return t[:MAX_ESTRATTO - 4000] + "\n[...]\n" + t[-3900:]

# ---------------- Claude ----------------
def estrai_json(testo):
    t = testo.strip()
    t = re.sub(r"^```[a-zA-Z]*\s*\n", "", t)
    t = re.sub(r"\n```\s*$", "", t).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise RuntimeError("nessun JSON nella risposta di Claude")
    return json.loads(t[i:j + 1])

def chiedi_claude(payload):
    r = requests.post(ABASE + "/v1/messages", headers={
            "x-api-key": AKEY, "anthropic-version": "2023-06-01",
            "content-type": "application/json"},
        data=json.dumps({"model": MODEL, "max_tokens": 2500, "system": SYSTEM,
            "messages": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]},
            ensure_ascii=False).encode("utf-8"), timeout=300)
    out = r.json() if r.content else {}
    if r.status_code != 200:
        msg = (out.get("error") or {}).get("message") or ("HTTP %d" % r.status_code)
        raise RuntimeError("API Claude: " + str(msg)[:200])
    testo = "\n".join(bl.get("text", "") for bl in out.get("content", []) if bl.get("type") == "text")
    return estrai_json(testo)

# ---------------- giro principale ----------------
def main():
    print("[%s] Incrocio automatico bandi <-> catalogo (modello %s, max %d bandi)" % (
        adesso().strftime("%Y-%m-%d %H:%M"), MODEL, MAXB))

    radar = leggi_radar()
    if radar.get("schema") != "fp-gestionale-concorsi/1":
        sys.exit("ERRORE: schema del JSON radar non riconosciuto: " + str(radar.get("schema")))
    bandi = radar.get("bandi") or []
    print("Radar: %d bandi (generato %s)" % (len(bandi), radar.get("generato", "?")))

    cat = leggi_tabella("tipo=eq.catalogo")
    materie_cat = []
    for r in cat:
        d = r.get("data") or {}
        materie_cat.append({"id": r["id"], "titolo": d.get("titolo") or "", "sid": d.get("sid") or ""})
    if not materie_cat:
        sys.exit("ERRORE: il Catalogo formativo e' vuoto nel database: carica prima il seed dalla scheda 📚 Catalogo.")
    per_id = {m["id"]: m for m in materie_cat}
    print("Catalogo: %d materie" % len(materie_cat))

    esistenti = set(r["id"] for r in leggi_tabella("tipo=eq.incrocio", select="id"))
    print("Incroci gia' presenti: %d" % len(esistenti))

    oggi = adesso().strftime("%Y-%m-%d")
    candidati = []
    for b in bandi:
        bid = str(b.get("id") or "")
        if not bid:
            continue
        scad = str(b.get("scadenza") or "")
        if str(b.get("stato") or "") == "Scaduto" or (scad and scad < oggi):
            continue
        if ("INC-" + bid) in esistenti and bid not in RIFAI:
            continue
        candidati.append(b)
    candidati.sort(key=lambda b: str(b.get("scadenza") or "9999"))
    da_fare = candidati[:MAXB]
    print("Bandi da incrociare: %d (in coda: %d)" % (len(da_fare), max(0, len(candidati) - MAXB)))

    fatti = senza_testo = errori = 0
    conta_temi = collections.Counter()
    for n, b in enumerate(da_fare, 1):
        bid = str(b["id"])
        try:
            testo = testo_del_bando(b)
            fonte = "bando" if len(testo) >= MIN_TESTO else "metadati"
            estratto = estratto_programma(testo) if fonte == "bando" else ""
            payload = {
                "bando": {"titolo": b.get("titolo") or "", "ente": b.get("ente") or "",
                          "profilo": b.get("profilo") or "", "comparto": b.get("comparto") or "",
                          "area": b.get("area") or "", "livello": b.get("livello") or "",
                          "tipo": b.get("tipo") or "", "materie": b.get("materie") or []},
                "programma": estratto,
                "materie": [{"id": m["id"], "titolo": m["titolo"]} for m in materie_cat],
            }
            dati = chiedi_claude(payload)
            mat = []
            for x in (dati.get("materie") or []):
                m = per_id.get((x or {}).get("id"))
                if m:
                    mat.append({"id": m["id"], "titolo": m["titolo"], "sid": m["sid"],
                                "motivo": str((x or {}).get("motivo") or "")})
            manc = []
            for x in (dati.get("mancanti") or [])[:12]:
                tema = str((x or {}).get("tema") or (x if isinstance(x, str) else "") or "").strip()
                if tema:
                    manc.append({"tema": tema, "motivo": str((x or {}).get("motivo") or "")})
                    conta_temi[tema.lower()] += 1
            nota = str(dati.get("nota") or "")
            if fonte == "metadati":
                nota = ("PDF del bando non leggibile o assente: bozza dai soli metadati. " + nota).strip()
            riga = {"id": "INC-" + bid, "tipo": "incrocio",
                    "data": {"bando_id": bid, "bando_titolo": b.get("titolo") or "",
                             "ente": b.get("ente") or "", "materie": mat, "mancanti": manc,
                             "nota": nota, "quando": oggi, "auto": True, "fonte": fonte,
                             "origine": "github"}}
            salva_incrocio(riga)
            fatti += 1
            if fonte == "metadati":
                senza_testo += 1
            print("  %d/%d %s — %d materie, %d temi scoperti%s" % (
                n, len(da_fare), (b.get("titolo") or bid)[:70], len(mat), len(manc),
                " [solo metadati]" if fonte == "metadati" else ""))
            time.sleep(1)
        except Exception as e:
            errori += 1
            print("  %d/%d %s — ERRORE: %s" % (n, len(da_fare), (b.get("titolo") or bid)[:70], str(e)[:160]))

    print("Fine giro: %d bozze salvate (%d dai soli metadati), %d errori, %d bandi ancora in coda." % (
        fatti, senza_testo, errori, max(0, len(candidati) - MAXB)))
    if conta_temi:
        print("Temi non coperti piu' frequenti in questo giro:")
        for tema, c in conta_temi.most_common(10):
            print("  %2d x %s" % (c, tema))
    if fatti == 0 and errori > 0:
        sys.exit("ERRORE: nessuna bozza salvata e %d errori" % errori)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.exit("ERRORE incrocio: %s" % e)
