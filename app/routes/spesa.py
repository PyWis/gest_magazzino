from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..models import EPS, OrdineSpesa, Prodotto, RigaSpesa, StatoSpesa, adesso, db
from ..utils import admin_richiesto, parse_qta

bp = Blueprint("spesa", __name__, url_prefix="/spesa")


@bp.route("/")
@admin_richiesto
def index():
    filtro = request.args.get("stato", "")
    query = OrdineSpesa.query
    if filtro in StatoSpesa.ETICHETTE:
        query = query.filter_by(stato=filtro)
    spese = query.order_by(OrdineSpesa.creato_il.desc()).all()
    return render_template("spesa/index.html", spese=spese, filtro=filtro)


def _leggi_form(spesa):
    f = request.form
    pids, qtas, prezzi = f.getlist("prodotto_id"), f.getlist("quantita"), f.getlist("prezzo")
    if not (len(pids) == len(qtas) == len(prezzi)):
        abort(400)
    errori, righe, righe_input = [], [], []
    for i, (pid, qs, ps) in enumerate(zip(pids, qtas, prezzi), start=1):
        pid, qs, ps = pid.strip(), qs.strip(), ps.strip()
        righe_input.append({"prodotto_id": pid, "quantita": qs, "prezzo": ps})
        if not pid and not qs and not ps:
            continue
        p = db.session.get(Prodotto, int(pid)) if pid.isdigit() else None
        q = parse_qta(qs)
        prezzo = parse_qta(ps) if ps else None
        if not p:
            errori.append(f"Riga {i}: seleziona un prodotto.")
        elif q is None or q <= 0:
            errori.append(f"Riga {i}: quantità non valida.")
        elif ps and (prezzo is None or prezzo < 0):
            errori.append(f"Riga {i}: prezzo non valido.")
        else:
            righe.append(RigaSpesa(prodotto=p, quantita=q, prezzo_unitario=prezzo))
    if not righe and not errori:
        errori.append("Aggiungi almeno un prodotto.")
    if not errori:
        spesa.fornitore = f.get("fornitore", "").strip()
        spesa.note = f.get("note", "").strip()
        spesa.righe = righe
    return errori, righe_input


def _render_form(spesa, righe_input):
    prodotti = Prodotto.query.filter_by(attivo=True).order_by(Prodotto.nome).all()
    return render_template("spesa/form.html", spesa=spesa, prodotti=prodotti, righe_input=righe_input)


@bp.route("/nuovo", methods=["GET", "POST"])
@admin_richiesto
def nuovo():
    spesa = OrdineSpesa(fornitore="", note="")
    righe_input = []
    if request.method == "POST":
        errori, righe_input = _leggi_form(spesa)
        if not errori:
            spesa.creato_da_id = current_user.id
            db.session.add(spesa)
            db.session.commit()
            flash(f"Ordine di spesa #{spesa.id} salvato come bozza.", "success")
            return redirect(url_for("spesa.dettaglio", sid=spesa.id))
        for e in errori:
            flash(e, "danger")
    return _render_form(spesa, righe_input)


@bp.route("/<int:sid>/modifica", methods=["GET", "POST"])
@admin_richiesto
def modifica(sid):
    spesa = db.get_or_404(OrdineSpesa, sid)
    if not spesa.modificabile:
        flash("Si possono modificare solo le bozze.", "warning")
        return redirect(url_for("spesa.dettaglio", sid=sid))
    righe_input = [{"prodotto_id": str(r.prodotto_id), "quantita": r.quantita,
                    "prezzo": r.prezzo_unitario} for r in spesa.righe]
    if request.method == "POST":
        errori, righe_input = _leggi_form(spesa)
        if not errori:
            db.session.commit()
            flash("Ordine di spesa aggiornato.", "success")
            return redirect(url_for("spesa.dettaglio", sid=sid))
        db.session.rollback()
        for e in errori:
            flash(e, "danger")
    return _render_form(spesa, righe_input)


@bp.route("/<int:sid>")
@admin_richiesto
def dettaglio(sid):
    return render_template("spesa/dettaglio.html", spesa=db.get_or_404(OrdineSpesa, sid))


@bp.route("/<int:sid>/stato", methods=["POST"])
@admin_richiesto
def cambia_stato(sid):
    spesa = db.get_or_404(OrdineSpesa, sid)
    azione = request.form.get("azione")

    if azione == "invia" and spesa.stato == StatoSpesa.BOZZA:
        spesa.stato, spesa.inviato_il = StatoSpesa.INVIATO, adesso()
        flash("Ordine segnato come inviato al fornitore.", "success")
    elif azione == "ricevi" and spesa.stato in (StatoSpesa.BOZZA, StatoSpesa.INVIATO):
        for r in spesa.righe:
            r.prodotto.giacenza = round(r.prodotto.giacenza + r.quantita, 3)
        spesa.stato, spesa.ricevuto_il = StatoSpesa.RICEVUTO, adesso()
        flash("Merce ricevuta: giacenze di magazzino aggiornate.", "success")
        if spesa.ordine_origine and spesa.ordine_origine.aperto:
            flash(f"Ora puoi evadere l'ordine #{spesa.ordine_origine.id} "
                  f"di {spesa.ordine_origine.docente.nome_completo}.", "info")
    elif azione == "annulla" and spesa.stato in (StatoSpesa.BOZZA, StatoSpesa.INVIATO):
        spesa.stato = StatoSpesa.ANNULLATO
        flash("Ordine di spesa annullato.", "info")
    else:
        flash("Operazione non consentita in questo stato.", "warning")
    db.session.commit()
    return redirect(url_for("spesa.dettaglio", sid=sid))


@bp.route("/da-sotto-scorta", methods=["POST"])
@admin_richiesto
def da_sotto_scorta():
    """Bozza con tutti i prodotti sotto scorta, quantità per tornare a 2× la scorta minima."""
    righe = []
    for p in Prodotto.query.filter_by(attivo=True).order_by(Prodotto.nome):
        if p.sotto_scorta:
            q = round(2 * p.scorta_minima - p.giacenza, 3)
            if q > EPS:
                righe.append(RigaSpesa(prodotto=p, quantita=q))
    if not righe:
        flash("Nessun prodotto sotto scorta.", "info")
        return redirect(url_for("prodotti.index"))
    spesa = OrdineSpesa(creato_da_id=current_user.id, righe=righe, note="Riordino prodotti sotto scorta")
    db.session.add(spesa)
    db.session.commit()
    flash(f"Bozza #{spesa.id} creata con {len(righe)} prodotti sotto scorta.", "success")
    return redirect(url_for("spesa.modifica", sid=spesa.id))
