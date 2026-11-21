from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

from ..magazzino import in_arrivo
from ..models import Movimento, Ordine, OrdineSpesa, Prodotto, StatoOrdine, StatoSpesa

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def home():
    if current_user.is_docente:
        return redirect(url_for("ordini.miei"))

    ordini_aperti = (Ordine.query.filter(Ordine.stato.in_(StatoOrdine.APERTI))
                     .order_by(Ordine.creato_il).all())
    prodotti = Prodotto.query.filter_by(attivo=True).order_by(Prodotto.nome).all()
    sotto_scorta = [p for p in prodotti if p.sotto_scorta]
    esauriti = sum(1 for p in prodotti if p.giacenza <= 0)
    spese_in_corso = (OrdineSpesa.query.filter(OrdineSpesa.stato.in_(StatoSpesa.APERTI))
                      .order_by(OrdineSpesa.creato_il.desc()).all())
    ultimi_movimenti = Movimento.query.order_by(Movimento.id.desc()).limit(8).all()
    return render_template("dashboard.html", ordini_aperti=ordini_aperti,
                           sotto_scorta=sotto_scorta, spese_in_corso=spese_in_corso,
                           arrivo=in_arrivo([p.id for p in sotto_scorta]),
                           n_prodotti=len(prodotti), esauriti=esauriti,
                           ultimi_movimenti=ultimi_movimenti)
