"""Scarica gli allegati PDF di un bando e ne estrae il testo."""
from __future__ import annotations
import logging, re
from pathlib import Path
import requests
from .models import Bando
from .sources.base import UA

log = logging.getLogger("radar")


def estrai_testo_pdf(path: Path, max_chars: int) -> str:
    try:
        from pypdf import PdfReader
        rd = PdfReader(str(path))
        txt = "\n".join((p.extract_text() or "") for p in rd.pages[:40])
        return re.sub(r"[ \t]+", " ", txt)[:max_chars]
    except Exception as e:
        log.warning("estrazione PDF fallita %s: %s", path.name, e)
        return ""


def scarica_bando(b: Bando, bandi_dir: str, max_chars: int) -> Bando:
    if b.testo or not b.url_allegati:
        return b
    d = Path(bandi_dir); d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-]", "_", b.id)
    for i, url in enumerate(b.url_allegati[:3]):        # max 3 allegati: bando + eventuali rettifiche
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": UA})
            ct = r.headers.get("content-type", "").lower()
            if r.status_code != 200 or not (r.content[:5] == b"%PDF-" or "pdf" in ct or "octet-stream" in ct):
                continue   # gli allegati inPA (/api/media/{id}) non hanno estensione: si guarda il contenuto
            p = d / f"{safe}_{i}.pdf"; p.write_bytes(r.content)
            b.pdf_locale = str(p)
            b.testo += estrai_testo_pdf(p, max_chars)
            if len(b.testo) > 2000:                      # abbastanza per classificare
                break
        except requests.RequestException as e:
            log.warning("download allegato fallito %s: %s", url, e)
    return b
