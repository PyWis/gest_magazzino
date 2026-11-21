"""Logica di magazzino: movimenti di giacenza, fabbisogni e merce in arrivo.

Tutte le variazioni di giacenza passano da qui, così:
  * ogni variazione viene registrata in `Movimento` (chi, quando, perché);
  * l'aggiornamento è fatto in SQL in modo atomico (giacenza = giacenza + delta),
    quindi due admin che lavorano insieme non si sovrascrivono a vicenda.
"""
from collections import defaultdict
from decimal import Decimal

from flask_login import current_user
from sqlalchemy import func, update

from .models import (D, ZERO, Movimento, Ordine, OrdineSpesa, Prodotto, RigaOrdine,
                     RigaSpesa, StatoOrdine, StatoSpesa, TipoMovimento, db)

TOLLERANZA = 0.0005  # mezza unità sull'ultima cifra decimale (3 decimali)


class GiacenzaInsufficiente(Exception):
    pass


class GiacenzaCambiata(Exception):
    pass


def _utente_id():
    try:
        return current_user.id if current_user.is_authenticated else None
    except Exception:  # fuori da una richiesta (es. comandi da terminale)
        return None


def _registra(prodotto, tipo, delta, nota="", ordine=None, ordine_spesa=None):
    db.session.refresh(prodotto, ["giacenza"])
    mov = Movimento(prodotto=prodotto, tipo=tipo, quantita=D(delta), giacenza_dopo=prodotto.giacenza,
                    nota=(nota or "")[:255], utente_id=_utente_id(),
                    ordine=ordine, ordine_spesa=ordine_spesa)
    db.session.add(mov)
    return mov


def muovi(prodotto, delta, tipo, nota="", ordine=None, ordine_spesa=None):
    """Aggiunge `delta` (con segno) alla giacenza in modo atomico e registra il movimento.
    Solleva GiacenzaInsufficiente se la giacenza andrebbe sotto zero."""
    delta = D(delta)
    db.session.flush()
    res = db.session.execute(
        update(Prodotto)
        .where(Prodotto.id == prodotto.id, Prodotto.giacenza + float(delta) >= -TOLLERANZA)
        .values(giacenza=func.round(Prodotto.giacenza + float(delta), 3))
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        raise GiacenzaInsufficiente(prodotto.nome)
    return _registra(prodotto, tipo, delta, nota, ordine, ordine_spesa)


def rettifica(prodotto, nuova_giacenza, giacenza_vista, nota):
    """Imposta la giacenza a un valore contato (inventario). Se nel frattempo qualcun altro
    l'ha modificata (giacenza attuale ≠ giacenza_vista) solleva GiacenzaCambiata."""
    nuova, vista = D(nuova_giacenza), D(giacenza_vista)
    db.session.flush()
    res = db.session.execute(
        update(Prodotto)
        .where(Prodotto.id == prodotto.id,
               Prodotto.giacenza.between(float(vista) - TOLLERANZA, float(vista) + TOLLERANZA))
        .values(giacenza=float(nuova))
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        db.session.refresh(prodotto, ["giacenza"])
        raise GiacenzaCambiata(prodotto.nome)
    return _registra(prodotto, TipoMovimento.RETTIFICA, nuova - vista, nota)


# ---------------------------------------------------------------- fabbisogni

def in_arrivo(prodotti_ids=None):
    """{prodotto_id: quantità ancora da ricevere} negli ordini di spesa aperti (bozze comprese)."""
    q = (db.session.query(RigaSpesa.prodotto_id,
                          func.sum(RigaSpesa.quantita - RigaSpesa.quantita_ricevuta))
         .join(OrdineSpesa).filter(OrdineSpesa.stato.in_(StatoSpesa.APERTI))
         .group_by(RigaSpesa.prodotto_id))
    if prodotti_ids is not None:
        q = q.filter(RigaSpesa.prodotto_id.in_(prodotti_ids))
    return defaultdict(lambda: ZERO, {pid: max(ZERO, D(v or 0)) for pid, v in q})


def domanda_aperta(prodotti_ids=None):
    """{prodotto_id: quantità ancora da consegnare} negli ordini docenti aperti."""
    q = (db.session.query(RigaOrdine.prodotto_id,
                          func.sum(RigaOrdine.quantita_richiesta - RigaOrdine.quantita_evasa))
         .join(Ordine).filter(Ordine.stato.in_(StatoOrdine.APERTI), RigaOrdine.prodotto_id.isnot(None))
         .group_by(RigaOrdine.prodotto_id))
    if prodotti_ids is not None:
        q = q.filter(RigaOrdine.prodotto_id.in_(prodotti_ids))
    return defaultdict(lambda: ZERO, {pid: max(ZERO, D(v or 0)) for pid, v in q})


def da_comprare(prodotto, domanda, arrivo, extra=ZERO):
    """Quanto serve ordinare: domanda aperta + extra (es. scorta) - giacenza - già in arrivo."""
    return max(ZERO, D(Decimal(domanda) + Decimal(extra) - prodotto.giacenza - Decimal(arrivo)))


# ---------------------------------------------------------------- conversioni

def collega_riga(riga, prodotto, quantita_manuale=None):
    """Collega una richiesta "Altro" a un prodotto, convertendo la quantità nell'unità
    del prodotto. Restituisce un messaggio d'errore oppure None."""
    if riga.quantita_evasa and riga.quantita_evasa > 0:
        return f"«{riga.nome}»: la riga ha già delle consegne, non si può ricollegare."
    da, a = riga.unita, prodotto.unita
    if quantita_manuale is not None:
        nuova = D(quantita_manuale)
        if nuova <= 0:
            return f"«{riga.nome}»: quantità convertita non valida."
    elif da.id == a.id:
        nuova = riga.quantita_richiesta
    else:
        nuova = da.converti(riga.quantita_richiesta, a)
        if nuova is None:
            return (f"«{riga.nome}»: il docente ha chiesto {fmt(riga.quantita_richiesta)} {da.simbolo} ma "
                    f"«{prodotto.nome}» si misura in {a.simbolo}. Indica la quantità in {a.simbolo}.")
    if da.id != a.id or nuova != riga.quantita_richiesta:
        if not riga.richiesta_originale:
            riga.richiesta_originale = f"{fmt(riga.quantita_richiesta)} {da.simbolo}"
    riga.prodotto = prodotto
    riga.unita = a
    riga.quantita_richiesta = nuova
    return None


def fmt(v):
    from .utils import fmt_qta
    return fmt_qta(v)
