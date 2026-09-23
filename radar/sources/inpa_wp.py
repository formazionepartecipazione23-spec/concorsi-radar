"""Fonte secondaria: REST WordPress di www.inpa.gov.it (sito informativo).

Endpoint pubblico verificato: /wp-json/wp/v2/posts. Pubblica gli annunci in
evidenza (concorsi nazionali, RIPAM, Ministeri): utile come integrazione e
come controllo di coerenza del portale.
"""
from __future__ import annotations
import html, logging, re
from .base import BaseSource
from ..models import Bando

log = logging.getLogger("radar")
DATE_RE = re.compile(r"(\d{1,2})[/\.](\d{1,2})[/\.](\d{4})")


def strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


class InpaWordPress(BaseSource):
    name = "inpa_wp"

    def fetch(self) -> list[Bando]:
        out = []
        for page in range(1, self.cfg.get("max_pages", 5) + 1):
            r = self.get(self.cfg["base_url"], params={"per_page": self.cfg.get("per_page", 100), "page": page,
                                                       "_fields": "id,title,link,date,content,excerpt"})
            posts = r.json()
            if not posts:
                break
            for p in posts:
                titolo = strip_html(p["title"]["rendered"])
                testo = strip_html(p.get("content", {}).get("rendered", ""))
                m = re.search(r"scadenz[ae][^0-9]{0,40}" + DATE_RE.pattern, testo, re.I)
                scad = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else ""
                ente = titolo.split(" – ")[0].split(" - ")[0] if (" – " in titolo or " - " in titolo) else ""
                links = re.findall(r'href="(https?://[^"]+\.pdf)"', p.get("content", {}).get("rendered", ""), re.I)
                b = Bando(id=f"inpawp:{p['id']}", fonte=self.name, ente=ente, titolo=titolo,
                          posti=self.guess_posti(titolo), tipo=self.guess_tipo(titolo),
                          data_pubblicazione=p["date"][:10], scadenza=scad,
                          url_bando=p["link"], url_allegati=links, testo=testo)
                b.hash_contenuto = self.make_hash(b.titolo, b.scadenza, b.posti)
                out.append(b)
            if len(posts) < self.cfg.get("per_page", 100):
                break
        log.info("inpa_wp: %d annunci", len(out))
        return out
