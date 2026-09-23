# ConcorsiRadar – monitoraggio nazionale dei concorsi PA per FP Formazione

Motore settimanale che raccoglie concorsi, mobilità e selezioni della PA (inPA, Gazzetta
Ufficiale), scarica i bandi, estrae le **materie d'esame**, le incrocia con il catalogo corsi
FP CGIL e segnala i **gap** da cui costruire nuovi percorsi. Produce un JSON importabile nel
FP Gestionale, un Excel per la segreteria e un report HTML nello stile del bollettino
FP CGIL Grosseto, ma per comparto e su scala nazionale.

## Come funziona

```
fonti (inPA portale, inPA WP, GU 4ª s.s.)
   └─> normalizzazione (Bando) ─> SQLite (storico, diff nuovo/aggiornato/scaduto)
         └─> download PDF + estrazione testo
               └─> classificazione (LLM Anthropic → fallback a regole): livello, area, comparto, materie
                     └─> matching materie ↔ catalogo_corsi.yaml (copertura %)
                           └─> gap analysis (materie richieste da ≥N bandi e non coperte)
                                 └─> export: JSON gestionale · XLSX · report HTML
```

L'incrocio si fa **sulle materie**, non sul titolo del profilo: "Istruttore amministrativo" a
Firenze e a Gavorrano hanno programmi diversi, e solo il bando lo dice.

## Avvio rapido

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...          # facoltativo: senza chiave si usano le regole a keyword

# 1. verifica che le fonti rispondano e stampa un record grezzo
python -m radar.run probe inpa_portale
python -m radar.run probe gazzetta

# 2. run settimanale completo
python -m radar.run weekly

# 3. prova offline con dati di esempio (i bandi del bollettino Grosseto + Sanità + Centrali)
python -m radar.run weekly --fixture fixtures/inpa_sample.json --skip-download
```

Output in `output/`: `concorsi_gestionale_AAAA_MM_GG.json`, `concorsi_AAAA_MM_GG.xlsx`,
`report_concorsi_AAAA_MM_GG.html`, più le copie a nome fisso `concorsi_gestionale_latest.json` e
`report_concorsi_latest.html` (quelle da far leggere al FP Gestionale), `radar.sqlite` (storico), `bandi/` (PDF, escluso da git).

## Schedulazione (GitHub Actions + GitHub Pages)

Il repository va tenuto **pubblico**: tratta solo dati pubblici, Actions è gratuito senza limiti di minuti
e GitHub Pages può servire gli output. Il gestionale (privato) resta fuori dal repository e legge il JSON da
`https://<utente>.github.io/concorsi-radar/concorsi_gestionale_latest.json`, che Pages serve con CORS aperto:
funziona anche con il gestionale aperto dal disco.

`.github/workflows/weekly.yml` esegue il run ogni lunedì alle 7:30, copia gli output in `docs/` (servita da
Pages: `index.html` è il report dell'ultima settimana) e archivia `output/radar.sqlite` nel repository.
Serve il secret `ANTHROPIC_API_KEY` e "Read and write permissions" per i workflow.
Prima del primo run su GitHub caricare `output/radar.sqlite` prodotto in locale (evita di riscaricare
tutti i PDF sul runner). Il database conserva max 8.000 caratteri di testo per bando (`TESTO_MAX` in db.py).

## Integrazione con FP Gestionale

Il JSON ha schema `fp-gestionale-concorsi/1`: un record per bando con `corsi_abbinati[]`
(`codice_corso`, `copertura`, `materie_scoperte`), flag `nuovo_questa_settimana`, e la sezione
`proposte_nuovi_percorsi`. Lato gestionale basta una scheda **Concorsi** con importazione
JSON (stesso pattern dell'import Excel esistente) che salvi in IndexedDB e mostri:
bandi attivi per comparto, abbinamenti, gap. I `codice_corso` del catalogo devono
coincidere con gli ID corso del gestionale.

## Cosa va fatto al primo run reale (importante)

1. **Endpoint inPA: verificati il 22/09/2026** direttamente dal browser (chiamate di rete di
   www.inpa.gov.it/bandi-e-avvisi). Ricerca `POST .../concorso-public-area/search-better?page=N&size=100`
   con body `{"text":"","status":["OPEN"]}`, dettaglio `GET .../concorso-public-area/{id}`, allegati
   `https://portale.inpa.gov.it/api/media/{mediaId}`. Alla data: 1.667 procedure aperte, 17 pagine.
   Nessuna autenticazione. Se in futuro `probe` restituisce errore, ripetere la verifica con gli
   strumenti sviluppatore del browser. Il sito WordPress (`inpa_wp`) è solo il blog istituzionale
   ed è disattivato di default.
2. **Gazzetta Ufficiale: verificata il 22/09/2026.** Indice `gazzettaufficiale.it/30giorni/concorsi`,
   sommari `/gazzetta/concorsi/caricaDettaglio?dataPubblicazioneGazzetta=...&numeroGazzetta=...`,
   atti `/atto/concorsi/caricaDettaglioAtto/originario?...codiceRedazionale=...`. Esclusi diari, avvisi,
   rettifiche e graduatorie. Se il markup cambia, il connettore alza `SourceError` e il run lo registra
   nella tabella `run` senza fermarsi.
3. **Catalogo corsi: ricostruito dal catalogo reale il 22/09/2026.** I 28 corsi di
   `catalogo_corsi.yaml` sono quelli pubblicati su fpformazione.it (categorie 22 e 40) con ID Moodle e
   URL reali; le materie vengono dal "Programma del corso" in pagina. I corsi con `note: da verificare`
   avevano il programma non elencato o troncato: controllare le materie a mano. Per tenere il catalogo
   allineato a Moodle: `python -m radar.catalogo_sync --token <token web service>` (aggiunge i corsi
   nuovi come bozza, segnala i rimossi, non tocca le materie curate a mano).
4. **Validazione umana.** La colonna `validato` in SQLite protegge una classificazione
   corretta a mano dalla riscrittura automatica. Prevedere ~30 minuti a settimana per
   controllare i casi con copertura tra 55% e 75% e i bandi senza testo.

## Roadmap suggerita

- **Fase 1 (2–3 settimane):** inPA + GU, comparti Sanità e Funzioni Locali, report settimanale ai territori.
- **Fase 2:** BUR regionali per le aziende sanitarie; report per regione/provincia (filtro `regione`).
- **Fase 3:** gap analysis operativa: collegare le materie scoperte al database del materiale
  didattico (moduli, lezioni, quiz GIFT) per comporre un nuovo percorso semi-automaticamente.
- Notifiche: mail alla segreteria con i soli bandi nuovi e le proposte sopra soglia.

## Struttura

```
config.yaml              parametri fonti, LLM, soglie, intestazione report
catalogo_corsi.yaml      corsi + tassonomia materie (il cuore del matching)
radar/sources/           connettori: inpa_portale, inpa_wp, gazzetta (+ base con retry)
radar/download.py        download allegati e testo PDF
radar/classify.py        LLM (JSON vincolato alla tassonomia) e regole di fallback
radar/match.py           copertura materie e gap analysis
radar/export.py          JSON gestionale, Excel, HTML
radar/db.py              SQLite: storico, diff, stati, log run
radar/run.py             CLI: weekly | export | probe
fixtures/                dati di esempio per test offline
.github/workflows/       cron settimanale
```
