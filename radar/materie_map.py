"""Mappa: titolo di sezione Moodle -> codici materia della tassonomia.
Usata da catalogo_sync per derivare le materie di un corso dalle sue sezioni ("Contenuto del corso").
Aggiungere qui una regola quando compare una sezione non riconosciuta (vedi `sezioni_non_mappate` nel YAML)."""
import re

SEZIONE_MATERIE = [
    (r"cos'è la pa|articolazione territoriale|organizzazione costituzionale|come si articola|articolazione territoriale dello stato|excursus storico", ["ORGANIZZAZIONE_PA", "DIR_COST"]),
    (r'diritto costituzionale', ["DIR_COST"]),
    (r'pubblico impiego|lavoro pubblico|codice di comportamento|smart working', ["PUBBL_IMPIEGO"]),
    (r'performance', ["PERFORMANCE"]),
    (r'enti locali|testo unico|267/2000', ["TUEL", "CONTAB_EL"]),
    (r'tributi comunali', ["DIR_TRIBUTARIO", "CONTAB_EL"]),
    (r'diritto tributario', ["DIR_TRIBUTARIO"]),
    (r'^diritto amministrativo|semplificazione amministrativa|amministrazione enti pubblici', ["DIR_AMM", "PROC_AMM"]),
    (r'amministrazione digitale|innovazione digitale|innovazione nella pa', ["DIGITALE_PA"]),
    (r'open government|trasparenza|prevenzione della corruzione|anticorruzione', ["ANTICORR"]),
    (r'contratti pubblici|contratti pubblic', ["CONTRATTI_PUBBLICI"]),
    (r'gdpr|privacy', ["PRIVACY"]),
    (r'economia delle amministrazioni|public management|pianificazione strategica|struttura organizzativa|gestione aziendale', ["MANAGEMENT_PA", "PROGRAMMAZIONE_PA"]),
    (r"europrogettazione|bilancio dell'unione|pnrr", ["EUROPROGETTAZIONE"]),
    (r'diritto penale|diritto processuale penale', ["DIR_PENALE_PA"]),
    (r'processuale penale', ["PROC_PENALE"]),
    (r'processuale civile|ordinamento giudiziario', ["PROC_CIVILE"]),
    (r'polizia giudiziaria', ["POLIZIA_GIUD"]),
    (r'informatica', ["INFORMATICA"]),
    (r'inglese', ["INGLESE"]),
    (r'unione europea', ["DIR_UE"]),
    (r"diritto internazionale|diritti dell'uomo", ["DIR_INTERNAZIONALE"]),
    (r'diritto consolare', ["DIR_CONSOLARE"]),
    (r'scienza delle finanze', ["SCIENZA_FINANZE"]),
    (r'bilancio e contabilità pubblica|contabilità pubblica', ["CONTAB_PUBBLICA", "BILANCIO_STATO"]),
    (r'contabilità aziendale', ["RAGIONERIA", "ECONOMIA_AZIENDALE"]),
    (r'economia politica|politica economica|economia del lavoro', ["ECONOMIA_AZIENDALE"]),
    (r'statistica|data science', ["STATISTICA"]),
    (r'politiche pubbliche', ["POLITICHE_PUBBLICHE"]),
    (r'controlli nella pubblica|controllo di gestione|sistemi di controllo', ["CONTROLLO_GESTIONE"]),
    (r'diritto del lavoro|legislazione sociale', ["DIR_LAVORO"]),
    (r'povertà|inclusione|fragili', ["SERVIZI_SOCIALI"]),
    (r'diritto civile', ["DIR_CIVILE"]),
    (r'commerciale', ["DIR_COMMERCIALE"]),
    (r'beni culturali|patrimonio culturale|paesaggio', ["BENI_CULTURALI", "AMBIENTE"]),
    (r'codice ambientale', ["AMBIENTE"]),
    (r'comunicazione e marketing|comunicazione pubblica', ["COMUNICAZIONE_PA"]),
    (r'sicurezza nei luoghi di lavoro|^la sicurezza$', ["SICUREZZA_LAVORO"]),
    (r'sistema sanitario nazionale|legge sanitaria|protagonisti del sistema sanitario', ["LEGISLAZ_SANITARIA", "ORG_SSN"]),
    (r'sanità digitale', ["SANITA_DIGITALE", "DIGITALE_PA"]),
    (r'etica professionale', ["DEONTOLOGIA_SAN"]),
    (r'pre-selezione|prova scritta|prova pratica|prova orale|questionari concorso oss', ["ASSISTENZA_OSS"]),
    (r'competenze trasversali|soft skills|situazional|completamento dei brani', ["SITUAZIONALI"]),
    (r'logic|preselettiv|preselezione|ragionamento', ["LOGICA"]),
    (r"storia d'italia|chimica|fisica", ["CULTURA_GENERALE"]),
    (r'camera di commercio', ["ORD_CAMERALE"]),
    (r'agenzia delle entrate', ["DIR_TRIBUTARIO"])
]
IGNORA = re.compile(r"simulazion|questionario|webinar|benvenut|annunci|presentazione del corso|link di collegamento|registrazion|^prova$|calendario|forum", re.I)


def materie_da_sezioni(sezioni):
    """Restituisce (codici ordinati, sezioni non riconosciute)."""
    out, non_mappate = set(), []
    for s in sezioni:
        low = s.lower(); hit = False
        for rx, codes in SEZIONE_MATERIE:
            if re.search(rx, low):
                out.update(codes); hit = True
        if not hit and not IGNORA.search(s):
            non_mappate.append(s)
    return sorted(out), non_mappate
