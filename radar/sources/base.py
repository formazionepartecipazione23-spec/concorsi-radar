from __future__ import annotations
import hashlib, logging, re, time
import requests
from ..models import Bando

log = logging.getLogger("radar")
# 21/10/2026: il portale inPA ha smesso di rispondere allo User-Agent "ConcorsiRadar"
# (fonte ferma al 13/10 senza che nessuno se ne accorgesse): ci si presenta come un
# browser normale; il recapito resta nell'intestazione From, per correttezza.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class SourceError(Exception):
    """Fonte non raggiungibile o struttura cambiata: il run deve SEGNALARE, non fallire in silenzio."""


class BaseSource:
    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "it-IT,it;q=0.9",
            "From": "segreteria@fpformazione.it",
        })

    def get(self, url, **kw):
        for i in range(3):
            try:
                r = self.s.get(url, timeout=30, **kw)
                if r.status_code == 200:
                    return r
                log.warning("%s -> HTTP %s %s", url, r.status_code, (r.text or "")[:200].replace("\n", " "))
            except requests.RequestException as e:
                log.warning("%s -> %s", url, e)
            time.sleep(2 * (i + 1))
        raise SourceError(f"{self.name}: impossibile leggere {url}")

    def post(self, url, json=None, **kw):
        for i in range(3):
            try:
                r = self.s.post(url, json=json, timeout=30, **kw)
                if r.status_code == 200:
                    return r
                log.warning("%s -> HTTP %s %s", url, r.status_code, (r.text or "")[:200].replace("\n", " "))
            except requests.RequestException as e:
                log.warning("%s -> %s", url, e)
            time.sleep(2 * (i + 1))
        raise SourceError(f"{self.name}: impossibile chiamare {url}")

    def fetch(self) -> list[Bando]:  # da implementare
        raise NotImplementedError

    # ---- helper comuni --------------------------------------------------
    @staticmethod
    def make_hash(*parts) -> str:
        return hashlib.sha1("|".join(str(p or "") for p in parts).encode()).hexdigest()[:12]

    @staticmethod
    def guess_tipo(titolo: str) -> str:
        t = titolo.lower()
        if "mobilit" in t:
            return "Mobilità esterna"
        if "avviso" in t or "selezione" in t or "incarico" in t or "art. 110" in t:
            return "Selezione pubblica"
        if "stabilizzazione" in t:
            return "Stabilizzazione"
        return "Concorso pubblico"

    @staticmethod
    def sanifica_posti(posti, titolo: str):
        """InPA accetta valori-segnaposto (9999, 99999999) per elenchi di idonei, albi, graduatorie aperte:
        in quei casi i posti non sono definiti e non devono entrare nelle somme."""
        if posti is None:
            return None
        t = (titolo or "").lower()
        senza_posti = any(k in t for k in ("elenco di idonei", "elenchi di idonei", "elenco idonei", "albo ", "albo permanente",
                                           "short list", "manifestazione di interesse", "banca dati"))
        if posti >= 9999 or (posti >= 500 and senza_posti):
            return None
        return int(posti)

    @staticmethod
    def guess_posti(titolo: str):
        m = re.search(r"\b(?:n\.?\s*)?(\d{1,4})\s+(?:posti|unit[àa]|figure)", titolo.lower())
        return int(m.group(1)) if m else None
