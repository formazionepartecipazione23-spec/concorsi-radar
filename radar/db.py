"""Persistenza SQLite: storico bandi, run settimanali, diff nuovo/aggiornato/scaduto."""
from __future__ import annotations
import json, sqlite3, datetime as dt
from pathlib import Path
from .models import Bando

SCHEMA = """
CREATE TABLE IF NOT EXISTS bandi (
  id TEXT PRIMARY KEY, fonte TEXT, ente TEXT, titolo TEXT, profilo TEXT, posti INTEGER,
  tipo TEXT, comparto TEXT, regione TEXT, sede TEXT, data_pubblicazione TEXT, scadenza TEXT,
  stato TEXT, url_bando TEXT, url_allegati TEXT, pdf_locale TEXT, testo TEXT,
  livello TEXT, area TEXT, materie TEXT, requisiti TEXT, classificato_da TEXT,
  corsi_abbinati TEXT, hash_contenuto TEXT,
  primo_rilevamento TEXT, ultimo_rilevamento TEXT, validato INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS run (
  id INTEGER PRIMARY KEY AUTOINCREMENT, avviato TEXT, fonte TEXT, n_trovati INTEGER,
  n_nuovi INTEGER, esito TEXT, note TEXT
);
CREATE INDEX IF NOT EXISTS ix_bandi_scad ON bandi(scadenza);
"""
LIST_COLS = {"url_allegati", "materie", "corsi_abbinati"}
TESTO_MAX = 8000   # caratteri di testo bando conservati nel DB (tiene il file sotto i limiti di GitHub)


class DB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.cx = sqlite3.connect(path)
        self.cx.row_factory = sqlite3.Row
        self.cx.executescript(SCHEMA)

    # ---- bandi -------------------------------------------------------
    def upsert(self, b: Bando) -> str:
        """Restituisce 'nuovo' | 'aggiornato' | 'invariato'."""
        now = dt.datetime.now().isoformat(timespec="seconds")
        cur = self.cx.execute("SELECT hash_contenuto, primo_rilevamento, validato FROM bandi WHERE id=?", (b.id,))
        row = cur.fetchone()
        d = b.to_export(); d["testo"] = b.testo[:TESTO_MAX]   # il testo intero serve solo alla classificazione
        for c in LIST_COLS:
            d[c] = json.dumps(d[c], ensure_ascii=False)
        if row is None:
            d.update(primo_rilevamento=now, ultimo_rilevamento=now)
            cols = ",".join(d); qs = ",".join("?" * len(d))
            self.cx.execute(f"INSERT INTO bandi ({cols}) VALUES ({qs})", list(d.values()))
            return "nuovo"
        d["ultimo_rilevamento"] = now
        # non sovrascrivere una classificazione validata a mano
        if row["validato"]:
            for c in ("livello", "area", "materie", "requisiti", "classificato_da", "corsi_abbinati"):
                d.pop(c, None)
        sets = ",".join(f"{k}=?" for k in d)
        self.cx.execute(f"UPDATE bandi SET {sets} WHERE id=?", [*d.values(), b.id])
        return "aggiornato" if row["hash_contenuto"] != b.hash_contenuto else "invariato"

    def load(self, where: str = "1=1", params=()) -> list[Bando]:
        rows = self.cx.execute(f"SELECT * FROM bandi WHERE {where} ORDER BY scadenza", params).fetchall()
        out = []
        for r in rows:
            d = {k: r[k] for k in r.keys() if k in Bando.__dataclass_fields__}
            for c in LIST_COLS:
                d[c] = json.loads(d[c] or "[]")
            out.append(Bando(**d))
        return out

    def attivi(self, oggi: str | None = None) -> list[Bando]:
        oggi = oggi or dt.date.today().isoformat()
        return self.load("scadenza >= ? OR stato='Prove in corso'", (oggi,))

    def nuovi_da(self, iso: str) -> list[Bando]:
        return self.load("primo_rilevamento >= ?", (iso,))

    def aggiorna_stati(self, oggi: str | None = None):
        """Scaduto se la scadenza è passata; 'Prove in corso' entro 60 gg dalla scadenza."""
        oggi = oggi or dt.date.today().isoformat()
        lim = (dt.date.fromisoformat(oggi) - dt.timedelta(days=60)).isoformat()
        self.cx.execute("UPDATE bandi SET stato='Prove in corso' WHERE scadenza < ? AND scadenza >= ? AND stato!='Scaduto'", (oggi, lim))
        self.cx.execute("UPDATE bandi SET stato='Scaduto' WHERE scadenza < ?", (lim,))

    def log_run(self, fonte, n_trovati, n_nuovi, esito, note=""):
        self.cx.execute("INSERT INTO run (avviato,fonte,n_trovati,n_nuovi,esito,note) VALUES (?,?,?,?,?,?)",
                        (dt.datetime.now().isoformat(timespec="seconds"), fonte, n_trovati, n_nuovi, esito, note))

    def ultimo_run_ok(self, fonte) -> str | None:
        r = self.cx.execute("SELECT avviato FROM run WHERE fonte=? AND esito='ok' ORDER BY id DESC LIMIT 1", (fonte,)).fetchone()
        return r["avviato"] if r else None

    def commit(self):
        self.cx.commit()
