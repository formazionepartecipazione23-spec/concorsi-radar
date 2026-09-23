"""Sincronizza catalogo_corsi.yaml con il catalogo reale di fpformazione.it (Moodle).

Uso:  python -m radar.catalogo_sync --token <TOKEN>            (aggiorna titoli/URL, segnala corsi nuovi/rimossi)
Il token si crea in Moodle: Amministrazione del sito > Server > Web service > Gestisci token,
con un servizio che includa core_course_get_courses_by_field. In alternativa il token dell'app
Moodle Mobile ("moodle_mobile_app") funziona per la lettura dei corsi.

Cosa fa: legge i corsi delle categorie 22 (Preparazione ai concorsi) e 40 (territoriali); per ciascuno legge
le SEZIONI del corso (core_course_get_contents = scheda "Contenuto del corso") e ricava le materie con la mappa
in radar/materie_map.py; aggiorna titolo, URL, sezioni e materie; aggiunge i corsi nuovi; marca `stato: rimosso`
quelli non più in catalogo. Livello, comparti, enti_target e tipo_corso restano curati a mano.
Senza token, la stessa lettura si può fare dal browser (vedi README) incollando le sezioni in `sezioni_moodle`.
"""
from __future__ import annotations
import argparse, html, re, sys
import requests, yaml
from .classify import classify_rules
from .models import Bando
from .materie_map import materie_da_sezioni

BASE = "https://fpformazione.it"
CATEGORIE = [22, 40]


def ws(token, fn, **params):
    r = requests.get(f"{BASE}/webservice/rest/server.php", params={"wstoken": token, "wsfunction": fn,
                     "moodlewsrestformat": "json", **params}, timeout=60)
    r.raise_for_status(); data = r.json()
    if isinstance(data, dict) and data.get("exception"):
        sys.exit(f"Moodle: {data.get('message')}")
    return data


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--token", required=True); ap.add_argument("--file", default="catalogo_corsi.yaml")
    a = ap.parse_args()
    cat = yaml.safe_load(open(a.file, encoding="utf-8"))
    per_id = {c.get("moodle_id"): c for c in cat["corsi"]}
    visti = set()
    for cid in CATEGORIE:
        for m in ws(a.token, "core_course_get_courses_by_field", field="category", value=cid)["courses"]:
            if not m.get("visible", 1):
                continue
            visti.add(m["id"])
            summary = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", m.get("summary") or "")))
            if m["id"] in per_id:
                c = per_id[m["id"]]; c["titolo"] = m["fullname"]; c["url"] = f"{BASE}/course/view.php?id={m['id']}"; c.pop("stato", None)
            else:
                b = classify_rules(Bando(id="x", fonte="x", ente="", titolo=m["fullname"], testo=summary), cat["materie"])
                cat["corsi"].append({"codice_corso": f"FPF-{m['id']}", "moodle_id": m["id"], "tipo_corso": "dedicato",
                                     "titolo": m["fullname"], "ente_organizzatore": "FP Formazione e Partecipazione",
                                     "url": f"{BASE}/course/view.php?id={m['id']}", "livello": [b.livello or "tutti"],
                                     "comparti": [b.comparto or "Altro"], "enti_target": [], "materie": b.materie,
                                     "note": "NUOVO da Moodle: materie classificate automaticamente, DA RIVEDERE"})
                print("nuovo corso:", m["id"], m["fullname"])
    for c in cat["corsi"]:
        if c.get("moodle_id") and c["moodle_id"] not in visti:
            c["stato"] = "rimosso"; print("non più in catalogo:", c["codice_corso"], c["titolo"])
    yaml.SafeDumper.ignore_aliases = lambda *x: True
    open(a.file, "w", encoding="utf-8").write(yaml.safe_dump(cat, allow_unicode=True, sort_keys=False, width=110))
    print(f"catalogo aggiornato: {len(cat['corsi'])} corsi")


if __name__ == "__main__":
    main()
