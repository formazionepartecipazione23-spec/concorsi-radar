"""Export: JSON per FP Gestionale, Excel per la segreteria, report HTML per i territori."""
from __future__ import annotations
import datetime as dt, html, json
from collections import Counter, defaultdict
from pathlib import Path
from .models import Bando

STATO_COL = {"Attivo": "#d9f2d9", "Prove in corso": "#fff3cd", "Scaduto": "#eeeeee"}


def export_json_gestionale(bandi: list[Bando], proposte: list[dict], nuovi_ids: set[str], out: Path, meta: dict):
    """Formato pensato per una scheda 'Concorsi' del FP Gestionale: un record per bando,
    corsi abbinati per codice_corso, flag nuovo/aggiornato, più le proposte di nuovi percorsi."""
    payload = {
        "schema": "fp-gestionale-concorsi/1",
        "generato": dt.datetime.now().isoformat(timespec="seconds"),
        "meta": meta,
        "bandi": [{**b.to_export(), "nuovo_questa_settimana": b.id in nuovi_ids} for b in bandi],
        "proposte_nuovi_percorsi": proposte,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def export_xlsx(bandi: list[Bando], proposte: list[dict], tassonomia: dict, out: Path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    hdr_font, hdr_fill = Font(bold=True, color="FFFFFF", name="Arial"), PatternFill("solid", fgColor="C00000")
    body = Font(name="Arial", size=10)

    def sheet(ws, headers, rows, widths):
        ws.append(headers)
        for c in ws[1]:
            c.font, c.fill, c.alignment = hdr_font, hdr_fill, Alignment(wrap_text=True, vertical="center")
        for r in rows:
            ws.append(r)
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.font, c.alignment = body, Alignment(wrap_text=True, vertical="top")
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions

    ws = wb.active; ws.title = "Bandi"
    sheet(ws, ["Fonte", "Ente", "Profilo", "Posti", "Tipo", "Comparto", "Regione", "Livello", "Area",
               "Scadenza", "Stato", "Materie d'esame", "Corso FP CGIL abbinato", "Copertura", "Link bando", "Classificato da", "ID"],
          [[b.fonte, b.ente, b.profilo or b.titolo, b.posti, b.tipo, b.comparto, b.regione, b.livello, b.area,
            b.scadenza, b.stato, "; ".join(tassonomia[m]["label"] for m in b.materie if m in tassonomia),
            b.corsi_abbinati[0]["titolo"] if b.corsi_abbinati else "–",
            b.corsi_abbinati[0]["copertura"] if b.corsi_abbinati else None,
            b.url_bando, b.classificato_da, b.id] for b in bandi],
          [11, 28, 34, 6, 16, 16, 12, 12, 13, 11, 13, 45, 40, 9, 40, 10, 14])

    ws2 = wb.create_sheet("Proposte nuovi percorsi")
    sheet(ws2, ["Priorità", "Comparto", "Area", "Livello", "N. bandi", "di cui senza corso", "Posti totali",
                "Materie scoperte (n. bandi)", "Proposta di percorso", "Bandi esempio"],
          [[p["priorita"], p["comparto"], p["area"], p["livello"], p["n_bandi"], p["n_bandi_senza_corso"], p["posti_totali"],
            "; ".join(f"{m['label']} ({m['n_bandi']})" for m in p["materie_scoperte"]), p["proposta"],
            "\n".join(p["bandi_esempio"])] for p in proposte],
          [9, 18, 14, 12, 9, 12, 10, 50, 50, 50])

    ws3 = wb.create_sheet("Sintesi")
    ws3.append(["Comparto", "Area", "Bandi attivi", "Posti", "Con corso abbinato"])
    agg = defaultdict(lambda: [0, 0, 0])
    for b in bandi:
        a = agg[(b.comparto, b.area)]; a[0] += 1; a[1] += b.posti or 0; a[2] += 1 if b.corsi_abbinati else 0
    for (c, a), v in sorted(agg.items(), key=lambda x: -x[1][0]):
        ws3.append([c, a, *v])
    for c in ws3[1]:
        c.font, c.fill = hdr_font, hdr_fill
    for i, w in enumerate([22, 16, 12, 10, 18], 1):
        ws3.column_dimensions[get_column_letter(i)].width = w
    wb.save(out)


def export_html(bandi: list[Bando], proposte: list[dict], nuovi_ids: set[str], tassonomia: dict, out: Path, meta: dict):
    """Report nello stile del bollettino FP CGIL Grosseto, ma per comparto e nazionale."""
    e = html.escape
    oggi = dt.date.today().strftime("%d/%m/%Y")
    per_comp = defaultdict(list)
    for b in bandi:
        per_comp[b.comparto or "Altro"].append(b)

    def riga(b: Bando):
        corso = b.corsi_abbinati[0] if b.corsi_abbinati else None
        nuovo = ' <span class="new">NUOVO</span>' if b.id in nuovi_ids else ""
        if corso:
            tag = " <small>(dedicato)</small>" if corso.get("tipo_corso") == "dedicato" else ""
            corso_td = f"<td>{e(corso['titolo'])}{tag}</td><td class=c><a href='{e(corso['url'])}'>Corso</a> ({int(corso['copertura'] * 100)}%)</td>"
        else:
            corso_td = "<td>–</td><td class=c>–</td>"
        return (f"<tr><td>{e(b.ente)}</td><td>{e(b.profilo or b.titolo)}{nuovo}</td><td class=c>{b.posti or ''}</td>"
                f"<td>{e(b.tipo)}</td><td class=c>{e(b.scadenza)}</td>"
                f"<td class=c style='background:{STATO_COL.get(b.stato, '#fff')}'><b>{e(b.stato)}</b></td>"
                f"<td class=c><a href='{e(b.url_bando)}'>Bando</a></td>{corso_td}</tr>")

    sezioni = ""
    for i, (comp, lst) in enumerate(sorted(per_comp.items(), key=lambda x: -len(x[1])), 1):
        righe = "\n".join(riga(b) for b in sorted(lst, key=lambda b: (b.stato != "Attivo", b.scadenza)))
        sezioni += f"""<h2>{i}. {e(comp.upper())} <small>({len(lst)} procedure)</small></h2>
<table><thead><tr><th>Ente</th><th>Profilo</th><th>Posti</th><th>Tipo</th><th>Scadenza</th><th>Stato</th><th>Bando</th><th>Corso FP CGIL</th><th>Link corso</th></tr></thead>
<tbody>{righe}</tbody></table>"""

    prop = ""
    for p in proposte:
        mat = "; ".join(f"{e(m['label'])} ({m['n_bandi']})" for m in p["materie_scoperte"])
        prop += (f"<tr><td class=c>{p['priorita']}</td><td>{e(p['comparto'])}</td><td>{e(p['area'])} / {e(p['livello'])}</td>"
                 f"<td class=c>{p['n_bandi']} ({p['n_bandi_senza_corso']} senza corso)</td><td class=c>{p['posti_totali']}</td><td>{mat}</td></tr>")

    n_nuovi = sum(1 for b in bandi if b.id in nuovi_ids)
    n_con_corso = sum(1 for b in bandi if b.corsi_abbinati)
    stats = Counter(b.fonte for b in bandi)
    doc = f"""<!doctype html><html lang=it><head><meta charset=utf-8><title>{e(meta['titolo'])}</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;font-size:10.5pt;color:#222;max-width:1200px;margin:24px auto;padding:0 16px}}
h1{{color:#c00000;margin:0 0 4px}} h2{{background:#c00000;color:#fff;padding:6px 10px;margin:28px 0 8px;font-size:12pt}}
h2 small{{font-weight:normal;opacity:.85}} .meta{{color:#555;font-style:italic;font-size:9.5pt}}
.kpi{{display:flex;gap:16px;margin:16px 0}} .kpi div{{background:#f6f6f6;border-left:4px solid #c00000;padding:8px 14px}}
.kpi b{{font-size:18pt;display:block}}
table{{width:100%;border-collapse:collapse;font-size:9.5pt}} th{{background:#c00000;color:#fff;padding:6px;text-align:left}}
td{{border-bottom:1px solid #ddd;padding:5px 6px;vertical-align:top}} tr:nth-child(even) td{{background:#fafafa}}
.c{{text-align:center}} .new{{background:#ffcc00;color:#000;font-size:8pt;font-weight:bold;padding:1px 4px;border-radius:3px}}
a{{color:#0645ad}} footer{{margin-top:32px;color:#777;font-size:9pt;border-top:1px solid #ccc;padding-top:8px}}
@media print{{h2{{break-after:avoid}} tr{{break-inside:avoid}}}}
</style></head><body>
<header><div><b>{e(meta['ente'])}</b><br><span class=meta>{e(meta['contatti'])}</span></div>
<p style="text-align:right">Aggiornato al {oggi}</p></header>
<h1>{e(meta['titolo'])}</h1>
<p class=meta>Monitoraggio automatico settimanale. Fonti: portale inPA (Funzioni Locali, Centrali, Sanità, Ricerca), sito inPA, Gazzetta Ufficiale 4ª Serie Speciale.
Le materie d'esame sono estratte dal testo del bando; l'abbinamento ai corsi indica la percentuale di materie coperte. Verificare sempre il bando originale.</p>
<div class=kpi><div><b>{len(bandi)}</b>procedure monitorate</div><div><b>{n_nuovi}</b>nuove questa settimana</div>
<div><b>{sum(b.posti or 0 for b in bandi)}</b>posti complessivi</div><div><b>{n_con_corso}</b>con corso FP CGIL abbinato</div>
<div><b>{len(proposte)}</b>proposte di nuovi percorsi</div></div>
{sezioni}
<h2>PROPOSTE DI NUOVI PERCORSI FORMATIVI <small>(gap analysis)</small></h2>
<p class=meta>Combinazioni comparto/area/livello con materie richieste da più bandi e non coperte dai corsi a catalogo. Priorità = n. bandi pesato per quelli senza alcun corso.</p>
<table><thead><tr><th>Priorità</th><th>Comparto</th><th>Area / Livello</th><th>Bandi</th><th>Posti</th><th>Materie scoperte (n. bandi)</th></tr></thead><tbody>{prop or '<tr><td colspan=6>Nessun gap sopra soglia.</td></tr>'}</tbody></table>
<footer>Fonti lette in questo run: {', '.join(f'{k} ({v})' for k, v in stats.items())}. Generato da ConcorsiRadar – {e(meta['ente'])}.</footer>
</body></html>"""
    out.write_text(doc, encoding="utf-8")
