"""Gazzetta Ufficiale - 4ª Serie Speciale «Concorsi ed Esami» (martedì e venerdì).

VERIFICATO IL 22/09/2026:
  indice ultimi 30 giorni: https://www.gazzettaufficiale.it/30giorni/concorsi
     -> link ai fascicoli: /gazzetta/concorsi/caricaDettaglio?dataPubblicazioneGazzetta=YYYY-MM-DD&numeroGazzetta=NN&elenco30giorni=true
  sommario fascicolo: sezioni in maiuscolo (AMMINISTRAZIONI CENTRALI, ENTI DI RICERCA, UNIVERSITA' ..., ENTI LOCALI,
     AZIENDE SANITARIE LOCALI ED ALTRE ISTITUZIONI SANITARIE, ALTRI ENTI, DIARI), poi per ogni atto DUE link
     allo stesso URL /atto/concorsi/caricaDettaglioAtto/originario?atto.dataPubblicazioneGazzetta=...&atto.codiceRedazionale=25E03165 :
     il primo con il tipo ("CONCORSO (scad. 30 giugno 2025)", "MOBILITA' (scad. ...)", "AVVISO", "DIARIO", "RETTIFICA"),
     il secondo con il titolo "... (25E03165) Pag. 8". L'ente è il testo in maiuscolo che precede il primo link.
Copre Sanità e Funzioni Centrali, dove la GU resta pubblicazione legale; il testo dell'atto (pagina originario)
riporta di norma le materie d'esame e il rimando al sito dell'ente.
"""
from __future__ import annotations
import html, logging, re
from .base import BaseSource, SourceError
from ..models import Bando

log = logging.getLogger("radar")

SEZIONI = ["AMMINISTRAZIONI CENTRALI", "ENTI PUBBLICI STATALI", "ENTI DI RICERCA", "UNIVERSITA' ED ALTRI ISTITUTI DI ISTRUZIONE",
           "ENTI LOCALI", "AZIENDE SANITARIE LOCALI ED ALTRE ISTITUZIONI SANITARIE", "ALTRI ENTI", "DIARI", "REGIONI"]
SEZIONE_COMPARTO = {"AMMINISTRAZIONI CENTRALI": "Funzioni Centrali", "ENTI PUBBLICI STATALI": "Funzioni Centrali",
                    "ENTI DI RICERCA": "Istruzione e Ricerca", "UNIVERSITA' ED ALTRI ISTITUTI DI ISTRUZIONE": "Istruzione e Ricerca",
                    "ENTI LOCALI": "Funzioni Locali", "REGIONI": "Regioni ed Enti Locali",
                    "AZIENDE SANITARIE LOCALI ED ALTRE ISTITUZIONI SANITARIE": "Sanità", "ALTRI ENTI": "Altro"}
MESI = {m: i for i, m in enumerate(["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
                                     "settembre", "ottobre", "novembre", "dicembre"], 1)}
TIPI_ESCLUSI_DEFAULT = {"DIARIO", "AVVISO", "RETTIFICA", "AVVISO DI RETTIFICA", "GRADUATORIA"}   # non sono bandi
ATTO_RE = re.compile(r'<a[^>]+href="([^"]*caricaDettaglioAtto/originario\?[^"]*codiceRedazionale=(\w+)[^"]*)"[^>]*>(.*?)</a>', re.S | re.I)


def testo(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


MINUSCOLE = {"di", "del", "della", "dello", "dei", "degli", "delle", "e", "ed", "per", "la", "il", "a", "in", "al", "alla", "-"}


def nome_ente(s: str) -> str:
    if not s or not s.isupper():
        return s or ""
    words = [w.lower() if w.lower() in MINUSCOLE else w.capitalize() for w in s.split()]
    words[0] = words[0].capitalize()
    return " ".join(words).replace("Asl", "ASL").replace("Aou", "AOU").replace("Irccs", "IRCCS").replace("Cnr", "CNR").replace("Inps", "INPS")


def parse_scad(s: str) -> str:
    m = re.search(r"scad\.\s*(\d{1,2})\s+([a-zà]+)\s+(\d{4})", s, re.I)
    if not m or m.group(2).lower() not in MESI:
        return ""
    return f"{m.group(3)}-{MESI[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


class GazzettaConcorsi(BaseSource):
    name = "gazzetta"

    def ultimi_fascicoli(self) -> list[tuple[str, str]]:
        """[(url_sommario, data_pubblicazione)] degli ultimi N fascicoli, dal più recente."""
        r = self.get(f"{self.cfg['base_url']}/30giorni/concorsi")
        found = re.findall(r'href="([^"]*gazzetta/concorsi/caricaDettaglio\?dataPubblicazioneGazzetta=(\d{4}-\d{2}-\d{2})[^"]*)"', r.text)
        if not found:
            raise SourceError("gazzetta: nessun fascicolo nell'indice 30 giorni -> markup cambiato")
        seen, out = set(), []
        for href, data in found:
            if data not in seen:
                seen.add(data); out.append((html.unescape(href if href.startswith("http") else self.cfg["base_url"] + href), data))
        out.sort(key=lambda x: x[1], reverse=True)
        return out[: self.cfg.get("ultimi_fascicoli", 2)]

    def parse_sommario(self, page_html: str, pubb: str) -> list[Bando]:
        # Isola il sommario e lavora sul testo con i link come marcatori
        start = page_html.find("Sommario"); body = page_html[start:] if start > 0 else page_html
        matches = list(ATTO_RE.finditer(body))
        escl = set(self.cfg.get("tipi_esclusi", TIPI_ESCLUSI_DEFAULT))
        out, sezione, i = [], "", 0
        prev_end, ente_corrente = 0, ""
        while i < len(matches):
            m = matches[i]
            tipo_txt = testo(m.group(3))
            # testo fra il link precedente e questo: contiene eventuale sezione ed ente
            gap = testo(body[prev_end:m.start()])
            for s in SEZIONI:
                if s in gap:
                    sezione = s; gap = gap.split(s, 1)[1].strip()
            gap = gap.strip(" -–:")
            if gap:                      # l'ente compare una volta sola per gruppo di atti
                ente_corrente = gap
            ente = ente_corrente
            # secondo link con lo stesso codice = titolo
            titolo, codice = "", m.group(2)
            if i + 1 < len(matches) and matches[i + 1].group(2) == codice:
                titolo = testo(matches[i + 1].group(3)); i += 1
            prev_end = matches[i].end(); i += 1
            tipo_base = re.sub(r"\s*\(.*", "", tipo_txt).strip().upper()
            if tipo_base in escl or not titolo:
                continue
            titolo = re.sub(r"\s*\(\w+\)\s*Pag\.\s*\d+\s*$", "", titolo)
            href = html.unescape(m.group(1)); href = href if href.startswith("http") else self.cfg["base_url"] + href
            b = Bando(id=f"gu:{codice}", fonte=self.name, ente=nome_ente(ente),
                      titolo=titolo, profilo=self._profilo(titolo), posti=self._posti(titolo),
                      tipo="Mobilità esterna" if "MOBILIT" in tipo_base else ("Concorso pubblico" if "CONCORSO" in tipo_base else "Selezione pubblica"),
                      comparto=SEZIONE_COMPARTO.get(sezione, ""), data_pubblicazione=pubb, scadenza=parse_scad(tipo_txt),
                      url_bando=href, url_allegati=[])
            b.hash_contenuto = self.make_hash(b.titolo, b.scadenza)
            out.append(b)
        return out

    @staticmethod
    def _profilo(t: str) -> str:
        m = re.search(r"post[oi] di ([^,.;]+?)(?:,| a tempo| presso| per |\.|$)", t, re.I)
        return m.group(1).strip() if m else ""

    NUM = {"un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7, "otto": 8, "nove": 9,
           "dieci": 10, "undici": 11, "dodici": 12, "quindici": 15, "venti": 20, "trenta": 30, "cinquanta": 50, "cento": 100}

    def _posti(self, t: str):
        m = re.search(r"copertura di (\w+) post", t, re.I)
        if not m:
            return self.guess_posti(t)
        w = m.group(1).lower()
        return int(w) if w.isdigit() else self.NUM.get(w)

    def testo_atto(self, b: Bando) -> Bando:
        """Scarica la pagina dell'atto (testo integrale GU): contiene spesso le materie d'esame."""
        try:
            r = self.get(b.url_bando)
            art = re.search(r'<div[^>]+class="[^"]*testo[^"]*"[^>]*>(.*?)</div>\s*</div>', r.text, re.S) or re.search(r"<body.*?>(.*)</body>", r.text, re.S)
            b.testo = testo(art.group(1))[:60000] if art else ""
        except SourceError as e:
            log.warning("atto GU non leggibile %s: %s", b.id, e)
        return b

    def fetch(self) -> list[Bando]:
        out = []
        for url, pubb in self.ultimi_fascicoli():
            r = self.get(url)
            found = self.parse_sommario(r.text, pubb)
            log.info("gazzetta %s: %d atti", pubb, len(found))
            out += found
        if self.cfg.get("testo_atto", True):
            for b in out:
                self.testo_atto(b)
        return out
