"""Fonte principale: Portale del Reclutamento inPA — backend REST "concorsi-smart".

VERIFICATO IL 22/09/2026 con il browser (chiamate di rete del sito www.inpa.gov.it/bandi-e-avvisi):

  POST https://portale.inpa.gov.it/concorsi-smart/api/concorso-public-area/search-better?page=N&size=100
       body JSON: {"text": "", "status": ["OPEN"]}      (status come LISTA; stringa -> HTTP 500)
       risposta: pagina Spring {content:[...], totalElements, totalPages, last, ...}
       ordinamento: dataPubblicazione DESC.  Il 22/09/2026: 1.667 procedure aperte (75.373 totali).
       campi record: id, codice, titolo, descrizioneBreve, figuraRicercata, dataPubblicazione,
       dataScadenza (ISO UTC), tipoProcedura (es. TITOLI_COLLOQUIO), numPosti, statusLabel,
       calculatedStatus, entiRiferimento[str], sedi[str], settori[str], categorie[str], allegatoMediaId
  GET  https://portale.inpa.gov.it/concorsi-smart/api/concorso-public-area/{id}
       dettaglio: company.name, sedi[{regioneDenominazione, provinciaDenominazione}], categorie[{name}],
       settori[{name}], requisitiSpecifici, descrizione, linkGazzettaUfficiale, linkSitoPA,
       allegati[{mediaId, label, tipo (BANDO_CONCORSO|...), sequence}]
  GET  https://portale.inpa.gov.it/api/media/{mediaId}            -> file PDF dell'allegato
  Pagina web del bando: https://www.inpa.gov.it/bandi-e-avvisi/dettaglio-bando-avviso/?concorso_id={id}

Categorie (filtro categoriaId): Concorso, Selezione Professionisti ed Esperti, Concorsi DFP – Formez Pa,
Avvisi di mobilità, Scelta PA/sede, Procedure Straordinarie, Bando Apprendistato, Avvisi OIV.
"""
from __future__ import annotations
import logging
from .base import BaseSource, SourceError
from ..models import Bando

log = logging.getLogger("radar")

TIPO_PROCEDURA = {
    "TITOLI_COLLOQUIO": "Per titoli e colloquio", "TITOLI_ESAMI": "Per titoli ed esami",
    "ESAMI": "Per esami", "TITOLI": "Per soli titoli", "COLLOQUIO": "Per colloquio",
}
CATEGORIA_TIPO = {
    "Avvisi di mobilità": "Mobilità esterna", "Concorso": "Concorso pubblico",
    "Concorsi DFP – Formez Pa": "Concorso pubblico", "Selezione Professionisti ed Esperti": "Selezione pubblica",
    "Procedure Straordinarie": "Stabilizzazione", "Avvisi OIV": "Selezione pubblica", "Scelta PA/sede": "Altro",
    "Bando Apprendistato": "Altro",
}
# categorie che di norma non interessano la formazione concorsuale
CATEGORIE_ESCLUSE_DEFAULT = {"Scelta PA/sede", "Selezione Professionisti ed Esperti", "Avvisi OIV", "Bando Apprendistato"}


class InpaPortale(BaseSource):
    name = "inpa_portale"

    def _search_url(self, page: int) -> str:
        return f"{self.cfg['base_url']}{self.cfg['search_path']}?page={page}&size={self.cfg.get('page_size', 100)}"

    def search_page(self, page: int) -> dict:
        body = {"text": self.cfg.get("text", ""), "status": list(self.cfg.get("stato", ["OPEN"]))}
        for k in ("categoriaId", "regioneId", "settoreId"):
            if self.cfg.get(k):
                body[k] = self.cfg[k]
        return self.post(self._search_url(page), json=body).json()

    def detail(self, id_: str) -> dict:
        return self.get(f"{self.cfg['base_url']}{self.cfg['detail_path'].format(id=id_)}").json()

    def probe(self):
        data = self.search_page(0)
        return {"totalElements": data.get("totalElements"), "totalPages": data.get("totalPages"),
                "primo_record": data["content"][0] if data.get("content") else None}

    def normalize(self, raw: dict) -> Bando:
        id_ = raw["id"]
        enti = raw.get("entiRiferimento") or []
        sedi = raw.get("sedi") or []
        categorie = raw.get("categorie") or []
        cat = categorie[0] if categorie else ""
        posti = raw.get("numPosti")
        b = Bando(
            id=f"inpa:{id_}", fonte=self.name,
            ente=enti[0] if enti else "",
            titolo=(raw.get("titolo") or "").strip(),
            profilo=(raw.get("figuraRicercata") or "").strip(),
            posti=int(posti) if isinstance(posti, (int, float)) and posti > 0 else self.guess_posti(raw.get("titolo") or ""),
            tipo=CATEGORIA_TIPO.get(cat) or self.guess_tipo(raw.get("titolo") or ""),
            regione=sedi[0] if sedi else "",
            sede=sedi[1] if len(sedi) > 1 else "",
            data_pubblicazione=(raw.get("dataPubblicazione") or "")[:10],
            scadenza=(raw.get("dataScadenza") or "")[:10],
            stato="Attivo" if raw.get("calculatedStatus") == "OPEN" else "Prove in corso",
            url_bando=f"https://www.inpa.gov.it/bandi-e-avvisi/dettaglio-bando-avviso/?concorso_id={id_}",
            url_allegati=[f"{self.cfg['media_url']}/{raw['allegatoMediaId']}"] if raw.get("allegatoMediaId") else [],
        )
        b.requisiti = "; ".join(filter(None, [
            TIPO_PROCEDURA.get(raw.get("tipoProcedura") or "", raw.get("tipoProcedura") or ""),
            "Settore: " + ", ".join(raw.get("settori") or []) if raw.get("settori") else "",
        ]))
        b.hash_contenuto = self.make_hash(b.titolo, b.scadenza, b.posti, raw.get("allegatoMediaId"))
        b._categoria = cat  # usato solo per il filtro
        return b

    def arricchisci(self, b: Bando) -> Bando:
        """Dettaglio: tutti gli allegati (bando prima), ente ufficiale, requisiti, link GU."""
        try:
            d = self.detail(b.id.split(":", 1)[1])
        except SourceError as e:
            log.warning("dettaglio non disponibile %s: %s", b.id, e); return b
        if d.get("company", {}).get("name"):
            b.ente = d["company"]["name"]
        alleg = sorted(d.get("allegati") or [], key=lambda a: (a.get("tipo") != "BANDO_CONCORSO", a.get("sequence") or 99))
        urls = [f"{self.cfg['media_url']}/{a['mediaId']}" for a in alleg if a.get("mediaId")]
        if urls:
            b.url_allegati = urls
        if d.get("requisitiSpecifici"):
            b.requisiti = (b.requisiti + "; " if b.requisiti else "") + str(d["requisitiSpecifici"])[:400]
        if d.get("descrizione") and not b.testo:
            b.testo = str(d["descrizione"])
        return b

    def fetch(self) -> list[Bando]:
        escluse = set(self.cfg.get("categorie_escluse", CATEGORIE_ESCLUSE_DEFAULT))
        out, page = [], 0
        while page < self.cfg.get("max_pages", 40):
            data = self.search_page(page)
            items = data.get("content")
            if not isinstance(items, list):
                raise SourceError("inpa_portale: risposta senza 'content' -> struttura API cambiata")
            for raw in items:
                try:
                    b = self.normalize(raw)
                    if b._categoria in escluse:
                        continue
                    out.append(b)
                except Exception as e:
                    log.warning("record inpa scartato (%s): %s", raw.get("id"), e)
            if data.get("last", True):
                break
            page += 1
        log.info("inpa_portale: %d procedure su %s aperte (%s pagine)", len(out), data.get("totalElements"), data.get("totalPages"))
        if self.cfg.get("dettaglio", True):
            for b in out:
                self.arricchisci(b)
        return out
