from __future__ import annotations
import hashlib, logging, re, time
import requests
from ..models import Bando

log = logging.getLogger("radar")
UA = "ConcorsiRadar/0.1 (FP Formazione e Partecipazione; segreteria@fpformazione.it)"


class SourceError(Exception):
    """Fonte non raggiungibile o struttura cambiata: il run deve SEGNALARE, non fallire in silenzio."""


class BaseSource:
    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA

    def get(self, url, **kw):
        for i in range(3):
            try:
                r = self.s.get(url, timeout=30, **kw)
                if r.status_code == 200:
                    return r
                log.warning("%s -> HTTP %s", url, r.status_code)
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
                log.warning("%s -> HTTP %s", url, r.status_code)
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
    def guess_posti(titolo: str):
        m = re.search(r"\b(?:n\.?\s*)?(\d{1,4})\s+(?:posti|unit[àa]|figure)", titolo.lower())
        return int(m.group(1)) if m else None
