from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

from ..models import Ordine, OrdineSpesa, Prodotto, StatoOrdine, StatoSpesa

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def home():
    if current_user.is_docente:
        return redirect(url_for("ordini.miei"))

    ordini_aperti = (Ordine.query.filter(Ordine.stato.in_(StatoOrdine.APERTI))
                     .order_by(Ordine.creato_il).all())
    sotto_scorta = [p for p in Prodotto.query.filter_by(attivo=True).order_by(Prodotto.nome)
                    if p.sotto_scorta]
    spese_in_corso = (OrdineSpesa.query
                      .filter(OrdineSpesa.stato.in_([StatoSpesa.BOZZA, StatoSpesa.INVIATO]))
                      .order_by(OrdineSpesa.creato_il.desc()).all())
    return render_template("dashboard.html", ordini_aperti=ordini_aperti,
                           sotto_scorta=sotto_scorta, spese_in_corso=spese_in_corso)
