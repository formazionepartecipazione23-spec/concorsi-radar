"""Classificazione del bando: livello, area, comparto, materie d'esame (codici tassonomia).

Due motori: `llm` (Anthropic, output JSON vincolato alla tassonomia) e `rules`
(keyword sulla tassonomia). Il primo è quello buono; il secondo garantisce che
il run produca comunque un risultato se l'API non è disponibile.
"""
from __future__ import annotations
import json, logging, os, re
from .models import Bando

log = logging.getLogger("radar")

LIVELLI = ["operatore", "istruttore", "funzionario", "dirigente", "altro"]
AREE = ["amministrativo", "contabile", "tecnico", "vigilanza", "educativo", "sanitario", "informatico", "sociale", "altro"]
COMPARTI = ["Funzioni Locali", "Funzioni Centrali", "Sanità", "Istruzione e Ricerca", "Regioni ed Enti Locali", "Altro"]

LIVELLO_KW = {
    "dirigente": ["dirigente", "direttore", "comandante"],
    "funzionario": ["funzionario", "istruttore direttivo", "specialista", "elevata qualificazione", "eq ", " d ",
                    "collaboratore professionale", "collaboratore amministrativo professionale", "collaboratore tecnico professionale",
                    "ingegner", "architett", "geologo", "assistente sociale"],
    "istruttore": ["istruttore", "agente", "assistente", "educatore", "insegnante", "cat. c", "area istruttori", "area degli istruttori", "geometra"],
    "operatore": ["operatore", "collaboratore tecnico enti di ricerca", "esecutore", "autista", "manutentore", "socio sanitario", "oss "],
}
AREA_KW = {
    "vigilanza": ["polizia locale", "polizia municipale", "vigilanza", "agente"],
    "educativo": ["educativo", "educatore", "infanzia", "nido", "pedagogic", "insegnante"],
    "sanitario": ["infermier", "sanitari", "medico", "ostetric", "oss ", "tecnico di", "asl", "azienda ospedaliera", "ausl", "ulss", "asst"],
    "informatico": ["informatic", "sistemi informativi", "ict"],
    "contabile": ["contabil", "ragioneria", "bilancio", "economico", "statistic"],
    "tecnico": ["tecnico", "ingegner", "architett", "geometra", "geologo", "lavori pubblici", "manutentiv"],
    "sociale": ["assistente sociale", "servizi sociali", "welfare"],
    "amministrativo": ["amministrativ", "giuridic", "legale", "affari generali", "risorse umane"],
}
COMPARTO_KW = {
    "Sanità": ["azienda sanitaria", "azienda usl", "azienda unità sanitaria", "usl ", "asl ", "ausl", "ulss", "asst", "aou", "azienda ospedalier",
               "ospedal", "irccs", "asp ", "azienda zero", "policlinico", "istituto zooprofilattico", "ares "],
    "Funzioni Locali": ["comune di", "provincia di", "unione di comuni", "unione dei comuni", "città metropolitana", "camera di commercio"],
    "Regioni ed Enti Locali": ["regione "],
    "Istruzione e Ricerca": ["universit", "cnr", "consiglio nazionale delle ricerche", "accademia", "conservatorio", "inaf", "infn", "istituto nazionale di", "scuola superiore", "scuola normale"],
    "Funzioni Centrali": ["ministero", "agenzia", "inps", "inail", "aci", "automobile club", "autorità", "presidenza del consiglio"],
}


def _kw_pick(text: str, table: dict, default: str) -> str:
    text = " " + text.lower() + " "
    best, score = default, 0
    for k, kws in table.items():
        s = sum(text.count(kw) for kw in kws)
        if s > score:
            best, score = k, s
    return best


def classify_rules(b: Bando, tassonomia: dict) -> Bando:
    head = f"{b.ente} {b.titolo} {b.profilo}"
    full = f"{head} {b.testo}"
    b.livello = _kw_pick(head, LIVELLO_KW, "altro")
    b.area = _kw_pick(head, AREA_KW, "altro")
    b.comparto = b.comparto or _kw_pick(b.ente or head, COMPARTO_KW, "Altro")
    low = full.lower()
    mat = [code for code, m in tassonomia.items() if any(kw in low for kw in m["kw"])]
    if not b.testo:   # senza testo del bando, inferisci le materie tipiche dell'area
        mat = mat or DEFAULT_MATERIE.get(b.area, [])
    b.materie = sorted(set(mat))
    b.classificato_da = "rules"
    return b


DEFAULT_MATERIE = {
    "amministrativo": ["DIR_AMM", "PROC_AMM", "PUBBL_IMPIEGO", "ANTICORR", "PRIVACY", "DIGITALE_PA"],
    "contabile": ["CONTAB_PUBBLICA", "CONTAB_EL", "ARMONIZZ_CONT", "DIR_AMM"],
    "vigilanza": ["CODICE_STRADA", "POLIZIA_LOCALE", "SANZIONI_AMM", "DIR_PENALE_PA", "PROC_PENALE"],
    "educativo": ["PEDAGOGIA", "PSICOLOGIA_SVILUPPO", "LEGISLAZ_SCOLASTICA", "SERVIZI_EDUCATIVI"],
    "sanitario": ["LEGISLAZ_SANITARIA", "ORG_SSN", "DEONTOLOGIA_SAN", "PUBBL_IMPIEGO", "SICUREZZA_LAVORO"],
    "tecnico": ["TECNICA_EDILIZIA", "CONTRATTI_PUBBLICI", "AMBIENTE", "DIR_AMM"],
    "informatico": ["INFORMATICA_AVANZATA", "DIGITALE_PA", "PRIVACY"],
    "sociale": ["SERVIZI_SOCIALI", "DIR_AMM", "PRIVACY"],
}

PROMPT = """Sei un esperto di concorsi pubblici italiani. Analizza il bando e restituisci SOLO un JSON con:
- "livello": uno tra {livelli}
- "area": una tra {aree}
- "comparto": uno tra {comparti}
- "profilo": denominazione sintetica del profilo (max 80 caratteri)
- "posti": intero o null
- "tipo": "Concorso pubblico" | "Mobilità esterna" | "Selezione pubblica" | "Stabilizzazione" | "Altro"
- "scadenza": data ISO (YYYY-MM-DD) del termine domande, o "" se non deducibile
- "materie": elenco di codici scelti SOLO da questa tassonomia (le materie d'esame dichiarate nel bando o, se assenti, quelle chiaramente implicate dal profilo):
{tassonomia}
- "requisiti": titolo di studio e requisiti specifici, in una frase (max 200 caratteri)

ENTE: {ente}
TITOLO: {titolo}
PROFILO: {profilo}
TESTO BANDO (può essere parziale):
{testo}
"""


def classify_llm(b: Bando, tassonomia: dict, model: str, max_chars: int) -> Bando:
    import anthropic
    client = anthropic.Anthropic()   # ANTHROPIC_API_KEY da ambiente
    tass = "\n".join(f"  {c}: {m['label']}" for c, m in tassonomia.items())
    msg = client.messages.create(
        model=model, max_tokens=800,
        messages=[{"role": "user", "content": PROMPT.format(
            livelli=LIVELLI, aree=AREE, comparti=COMPARTI, tassonomia=tass,
            ente=b.ente, titolo=b.titolo, profilo=b.profilo, testo=(b.testo or "(non disponibile)")[:max_chars])}])
    raw = "".join(c.text for c in msg.content if c.type == "text")
    data = json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip())
    b.livello = data.get("livello") if data.get("livello") in LIVELLI else "altro"
    b.area = data.get("area") if data.get("area") in AREE else "altro"
    b.comparto = data.get("comparto") if data.get("comparto") in COMPARTI else (b.comparto or "Altro")
    b.profilo = data.get("profilo") or b.profilo
    b.posti = data.get("posti") if isinstance(data.get("posti"), int) else b.posti
    b.tipo = data.get("tipo") or b.tipo
    b.scadenza = b.scadenza or data.get("scadenza", "")
    b.materie = sorted({m for m in data.get("materie", []) if m in tassonomia})
    b.requisiti = data.get("requisiti", "")
    b.classificato_da = "llm"
    return b


def classify(b: Bando, tassonomia: dict, cfg: dict) -> Bando:
    if cfg.get("provider") == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return classify_llm(b, tassonomia, cfg.get("model", "claude-sonnet-4-6"), cfg.get("max_pdf_chars", 60000))
        except Exception as e:
            log.warning("LLM fallito su %s (%s)%s", b.id, e, " -> regole" if cfg.get("fallback_rules", True) else "")
            if not cfg.get("fallback_rules", True):
                raise
    return classify_rules(b, tassonomia)
