"""Incrocio bandi <-> corsi a catalogo e gap analysis.

Copertura = |materie del bando coperte dal corso| / |materie del bando|,
con vincoli su livello e comparto. Un corso è proposto se copertura >= soglia.
Il gap è l'insieme (materie richieste, livello) frequente nei bandi attivi e
non coperto da alcun corso: è la proposta di nuovo percorso.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from .models import Bando


def _compatibile(corso: dict, b: Bando) -> bool:
    liv_ok = "tutti" in corso["livello"] or not b.livello or b.livello in corso["livello"] or b.livello == "altro"
    comp_ok = not b.comparto or b.comparto in corso["comparti"] or b.comparto == "Altro"
    return liv_ok and comp_ok


def _ente_target(c: dict, b: Bando) -> bool:
    testo = f"{b.ente} {b.titolo}".lower()
    return any(k in testo for k in c.get("enti_target", []))


def match_bando(b: Bando, corsi: list[dict], soglia: float) -> Bando:
    """Copertura = materie del bando coperte / materie del bando.
    Corso 'dedicato' a un altro concorso: proposto solo se copre molto (soglia +0.15) o se l'ente coincide
    (bonus: è quasi certamente lo stesso concorso -> copertura 1.0)."""
    b.corsi_abbinati = []
    if not b.materie:
        return b
    mat = set(b.materie)
    for c in corsi:
        if not _compatibile(c, b):
            continue
        cop = len(mat & set(c["materie"])) / len(mat)
        dedicato = c.get("tipo_corso") == "dedicato"
        stesso_ente = dedicato and _ente_target(c, b) and cop >= 0.4   # ente coincide E materie plausibili
        if stesso_ente:
            cop = max(cop, 0.9)
        elif dedicato and cop < soglia + 0.15:
            continue
        if cop >= soglia:
            b.corsi_abbinati.append({"codice_corso": c["codice_corso"], "titolo": c["titolo"],
                                     "ente_organizzatore": c["ente_organizzatore"], "url": c["url"],
                                     "tipo_corso": c.get("tipo_corso", "generico"), "stesso_ente": stesso_ente,
                                     "copertura": round(cop, 2),
                                     "materie_scoperte": sorted(mat - set(c["materie"]))})
    b.corsi_abbinati.sort(key=lambda x: (-x["stesso_ente"], x["tipo_corso"] == "dedicato", -x["copertura"]))
    return b


def gap_analysis(bandi: list[Bando], corsi: list[dict], tassonomia: dict, soglia_gap: int) -> list[dict]:
    """Materie richieste da almeno `soglia_gap` bandi attivi e mai coperte dal miglior corso abbinato,
    raggruppate per (comparto, area) con indicazione dei livelli prevalenti -> ciascun gruppo è una proposta di nuovo percorso."""
    gruppi = defaultdict(lambda: {"bandi": [], "materie": Counter(), "posti": 0, "livelli": Counter()})
    for b in bandi:
        if not b.materie:
            continue
        best = b.corsi_abbinati[0] if b.corsi_abbinati else None
        scoperte = set(best["materie_scoperte"]) if best else set(b.materie)
        if not scoperte:
            continue
        g = gruppi[(b.comparto, b.area)]
        g["bandi"].append(b); g["posti"] += b.posti or 0; g["livelli"][b.livello or "altro"] += 1
        g["materie"].update(scoperte)
    proposte = []
    for (comp, area), g in gruppi.items():
        mat = [(m, n) for m, n in g["materie"].most_common() if n >= soglia_gap]
        if not mat:
            continue
        liv = "/".join(l for l, _ in g["livelli"].most_common(2))
        senza_corso = sum(1 for b in g["bandi"] if not b.corsi_abbinati)
        proposte.append({
            "comparto": comp, "area": area, "livello": liv,
            "n_bandi": len(g["bandi"]), "n_bandi_senza_corso": senza_corso, "posti_totali": g["posti"],
            "materie_scoperte": [{"codice": m, "label": tassonomia[m]["label"], "n_bandi": n} for m, n in mat],
            "proposta": f"Percorso {area} per {liv} ({comp}): "
                        + ", ".join(tassonomia[m]["label"] for m, _ in mat[:4]),
            "priorita": round(len(g["bandi"]) * (1 + senza_corso / max(len(g["bandi"]), 1)), 1),
            "bandi_esempio": [f"{b.ente} – {b.profilo or b.titolo}" for b in g["bandi"][:5]],
        })
    return sorted(proposte, key=lambda p: -p["priorita"])
