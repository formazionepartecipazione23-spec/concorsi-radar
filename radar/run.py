"""CLI ConcorsiRadar.

  python -m radar.run weekly            # run completo: fetch -> download -> classify -> match -> export
  python -m radar.run weekly --fixture fixtures/inpa_sample.json   # senza rete, per test/demo
  python -m radar.run probe inpa_portale   # stampa un record grezzo della fonte (verifica struttura API)
  python -m radar.run export            # rigenera gli output dal database senza rifare il fetch

21/10/2026: una fonte in errore non deve più passare sotto silenzio. Il run completa
comunque l'export (il file esce lo stesso), ma scrive output/FONTI_IN_ERRORE.txt:
il workflow lo legge e segna il giro ROSSO, così arriva la mail di GitHub.
(Caso reale: inPA ferma dal 13/10 per blocco dello User-Agent, nessuno avvisato.)
"""
from __future__ import annotations
import argparse, datetime as dt, json, logging, sys
from pathlib import Path
import yaml
from .db import DB
from .models import Bando
from .sources import REGISTRY
from .sources.base import SourceError
from .download import scarica_bando
from .classify import classify
from .match import match_bando, gap_analysis
from .export import export_json_gestionale, export_xlsx, export_html

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("radar")


def load_cfg(path):
    cfg = yaml.safe_load(open(path, encoding="utf-8"))
    cat = yaml.safe_load(open(Path(path).parent / "catalogo_corsi.yaml", encoding="utf-8"))
    corsi = [c for c in cat["corsi"] if c.get("stato") != "rimosso"]
    return cfg, corsi, cat["materie"]


def fetch_all(cfg, db: DB, fixture: str | None):
    bandi, errori = [], []
    if fixture:
        raw = json.load(open(fixture, encoding="utf-8"))
        for r in raw:
            b = Bando(**{k: v for k, v in r.items() if k in Bando.__dataclass_fields__})
            b.hash_contenuto = b.hash_contenuto or f"{hash((b.titolo, b.scadenza)) & 0xffffffff:x}"
            bandi.append(b)
        db.log_run("fixture", len(bandi), 0, "ok")
        return bandi, errori
    for name, scfg in cfg["sources"].items():
        if not scfg.get("enabled"):
            continue
        try:
            found = REGISTRY[name](scfg).fetch()
            bandi += found
            db.log_run(name, len(found), 0, "ok")
        except SourceError as e:
            # la fonte va segnalata: un run che tace e' peggio di un run che fallisce
            log.error("FONTE NON DISPONIBILE: %s", e)
            db.log_run(name, 0, 0, "errore", str(e))
            errori.append(f"{name}: {e}")
    return bandi, errori


def weekly(cfg, corsi, tassonomia, fixture=None, skip_download=False):
    db = DB(cfg["db_path"])
    da = dt.datetime.now().isoformat(timespec="seconds")
    bandi, errori = fetch_all(cfg, db, fixture)
    esiti = {"nuovo": 0, "aggiornato": 0, "invariato": 0}
    for b in bandi:
        esito = db.upsert(b)
        esiti[esito] += 1
        if esito == "invariato":
            continue
        if not skip_download:
            scarica_bando(b, cfg["bandi_dir"], cfg["classify"]["max_pdf_chars"])
        classify(b, tassonomia, cfg["classify"])
        match_bando(b, corsi, cfg["match"]["soglia_abbinamento"])
        db.upsert(b)
    db.aggiorna_stati()
    db.commit()
    log.info("bandi: %s", esiti)
    nuovi = {b.id for b in db.nuovi_da(da)}
    esporta(cfg, corsi, tassonomia, db, nuovi)
    # ---- 21/10: segnalazione RUMOROSA delle fonti in errore (dopo l'export) ----
    marker = Path(cfg["output_dir"]) / "FONTI_IN_ERRORE.txt"
    if errori:
        marker.write_text("\n".join(errori) + "\n", encoding="utf-8")
        log.error("ATTENZIONE: %d fonte/i NON hanno risposto (%s). Il file e' stato pubblicato comunque, "
                  "ma SENZA i bandi nuovi di queste fonti: i loro dati restano fermi all'ultimo giro buono.",
                  len(errori), "; ".join(errori))
    elif marker.exists():
        marker.unlink()


def esporta(cfg, corsi, tassonomia, db: DB, nuovi: set[str] | None = None):
    out = Path(cfg["output_dir"]); out.mkdir(parents=True, exist_ok=True)
    attivi = db.attivi()
    # ri-esegui il matching sul catalogo corrente (il catalogo puo' essere cambiato)
    for b in attivi:
        match_bando(b, corsi, cfg["match"]["soglia_abbinamento"])
    proposte = gap_analysis(attivi, corsi, tassonomia, cfg["match"]["soglia_gap"])
    nuovi = nuovi if nuovi is not None else set()
    tag = dt.date.today().strftime("%Y_%m_%d")
    meta = cfg["report"]
    def scrivi(fn, nome, *args):
        """Se il file e' aperto in Excel/browser (Windows lo blocca), scrive una copia con l'ora e prosegue."""
        try:
            fn(*args, out / nome)
        except PermissionError:
            alt = out / nome.replace(".", f"_{dt.datetime.now():%H%M}.", 1)
            log.warning("%s e' aperto in un altro programma: scrivo %s", nome, alt.name)
            fn(*args, alt)

    scrivi(lambda a, p_, pr, n, m, path: export_json_gestionale(a, pr, n, path, m), f"concorsi_gestionale_{tag}.json", attivi, None, proposte, nuovi, meta)
    scrivi(lambda a, pr, t, path: export_xlsx(a, pr, t, path), f"concorsi_{tag}.xlsx", attivi, proposte, tassonomia)
    scrivi(lambda a, pr, n, t, m, path: export_html(a, pr, n, t, path, m), f"report_concorsi_{tag}.html", attivi, proposte, nuovi, tassonomia, meta)
    # copie a nome fisso: sono quelle che il FP Gestionale (o una pagina web) legge sempre allo stesso indirizzo
    scrivi(lambda a, p_, pr, n, m, path: export_json_gestionale(a, pr, n, path, m), "concorsi_gestionale_latest.json", attivi, None, proposte, nuovi, meta)
    scrivi(lambda a, pr, n, t, m, path: export_html(a, pr, n, t, path, m), "report_concorsi_latest.html", attivi, proposte, nuovi, tassonomia, meta)
    log.info("export: %d bandi attivi, %d proposte -> %s", len(attivi), len(proposte), out)


def probe(cfg, fonte):
    src = REGISTRY[fonte](cfg["sources"][fonte])
    rec = src.probe() if hasattr(src, "probe") else src.fetch()[:1]
    print(json.dumps(rec, ensure_ascii=False, indent=2, default=str)[:4000])


def main(argv=None):
    ap = argparse.ArgumentParser(description="ConcorsiRadar")
    ap.add_argument("cmd", choices=["weekly", "export", "probe"])
    ap.add_argument("fonte", nargs="?")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--fixture", help="file JSON con bandi gia' normalizzati (test offline)")
    ap.add_argument("--skip-download", action="store_true")
    a = ap.parse_args(argv)
    cfg, corsi, tass = load_cfg(a.config)
    if a.cmd == "weekly":
        weekly(cfg, corsi, tass, a.fixture, a.skip_download)
    elif a.cmd == "export":
        esporta(cfg, corsi, tass, DB(cfg["db_path"]))
    elif a.cmd == "probe":
        probe(cfg, a.fonte or "inpa_portale")


if __name__ == "__main__":
    main()
