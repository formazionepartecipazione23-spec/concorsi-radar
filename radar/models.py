from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Bando:
    """Un concorso/mobilità/selezione, normalizzato indipendentemente dalla fonte."""
    id: str                     # <fonte>:<id_nativo>
    fonte: str                  # inpa_portale | inpa_wp | gazzetta
    ente: str
    titolo: str
    profilo: str = ""
    posti: Optional[int] = None
    tipo: str = ""              # Concorso pubblico | Mobilità esterna | Selezione pubblica | ...
    comparto: str = ""
    regione: str = ""
    sede: str = ""
    data_pubblicazione: str = ""   # ISO
    scadenza: str = ""             # ISO
    stato: str = "Attivo"          # Attivo | Prove in corso | Scaduto
    url_bando: str = ""
    url_allegati: list[str] = field(default_factory=list)
    pdf_locale: str = ""
    testo: str = ""                # testo estratto dal PDF/pagina (non esportato)
    # -- campi prodotti dalla classificazione --
    livello: str = ""              # istruttore | funzionario | dirigente | operatore | altro
    area: str = ""                 # amministrativo | contabile | tecnico | vigilanza | educativo | sanitario | informatico | altro
    materie: list[str] = field(default_factory=list)   # codici tassonomia
    requisiti: str = ""
    classificato_da: str = ""      # llm | rules
    # -- campi prodotti dal matching --
    corsi_abbinati: list[dict] = field(default_factory=list)  # [{codice_corso, titolo, copertura}]
    hash_contenuto: str = ""

    def to_export(self) -> dict:
        d = asdict(self)
        d.pop("testo", None)
        return d
