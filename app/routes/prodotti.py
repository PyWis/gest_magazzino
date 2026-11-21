from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_

from ..models import Prodotto, RigaOrdine, Unita, db
from ..utils import admin_richiesto, parse_qta

bp = Blueprint("prodotti", __name__, url_prefix="/magazzino")


@bp.route("/")
@admin_richiesto
def index():
    q = request.args.get("q", "").strip()
    filtro = request.args.get("filtro", "")
    query = Prodotto.query.filter_by(attivo=(filtro != "disattivati"))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Prodotto.nome.ilike(like), Prodotto.categoria.ilike(like)))
    prodotti = query.order_by(Prodotto.categoria, Prodotto.nome).all()
    if filtro == "sotto_scorta":
        prodotti = [p for p in prodotti if p.sotto_scorta]
    n_sotto_scorta = sum(1 for p in Prodotto.query.filter_by(attivo=True) if p.sotto_scorta)
    return render_template("prodotti/index.html", prodotti=prodotti, q=q, filtro=filtro,
                           n_sotto_scorta=n_sotto_scorta)


def _categorie():
    righe = db.session.query(Prodotto.categoria).filter(Prodotto.categoria != "").distinct()
    return sorted(r[0] for r in righe)


def _salva(prodotto):
    errori = []
    nome = request.form.get("nome", "").strip()
    unita_id = request.form.get("unita_id", "")
    giacenza = parse_qta(request.form.get("giacenza") or "0")
    scorta = parse_qta(request.form.get("scorta_minima") or "0")
    unita = db.session.get(Unita, int(unita_id)) if unita_id.isdigit() else None

    if not nome:
        errori.append("Il nome è obbligatorio.")
    elif (Prodotto.query.filter(func.lower(Prodotto.nome) == nome.lower(),
                                Prodotto.id != (prodotto.id or 0)).first()):
        errori.append("Esiste già un prodotto con questo nome.")
    if not unita:
        errori.append("Seleziona l'unità di misura.")
    if giacenza is None or giacenza < 0:
        errori.append("Giacenza non valida.")
    if scorta is None or scorta < 0:
        errori.append("Scorta minima non valida.")

    if not errori:
        prodotto.nome = nome
        prodotto.descrizione = request.form.get("descrizione", "").strip()
        prodotto.categoria = request.form.get("categoria", "").strip()
        prodotto.unita = unita
        prodotto.giacenza = giacenza
        prodotto.scorta_minima = scorta
        if "attivo" in request.form:  # campo presente solo in modifica
            prodotto.attivo = "1" in request.form.getlist("attivo")
    return errori


@bp.route("/nuovo", methods=["GET", "POST"])
@admin_richiesto
def nuovo():
    """Nuovo prodotto. Con ?da_riga=ID lo crea da una richiesta "Altro" di un docente
    e collega automaticamente quella riga d'ordine al prodotto."""
    riga = None
    da_riga = request.args.get("da_riga", "")
    if da_riga.isdigit():
        riga = db.session.get(RigaOrdine, int(da_riga))
        if riga and riga.prodotto_id:
            riga = None

    prodotto = Prodotto(giacenza=0, scorta_minima=0, attivo=True)
    if riga and request.method == "GET":
        prodotto.nome = riga.descrizione_libera
        prodotto.unita_id = riga.unita_id

    if request.method == "POST":
        errori = _salva(prodotto)
        if not errori:
            db.session.add(prodotto)
            if riga:
                riga.prodotto = prodotto
                riga.unita_id = prodotto.unita.id
            db.session.commit()
            flash(f"Prodotto «{prodotto.nome}» creato.", "success")
            if riga:
                return redirect(url_for("ordini.dettaglio", oid=riga.ordine_id))
            return redirect(url_for("prodotti.index"))
        for e in errori:
            flash(e, "danger")

    return render_template("prodotti/form.html", prodotto=prodotto, nuovo=True, riga=riga,
                           unita=Unita.query.order_by(Unita.nome).all(), categorie=_categorie())


@bp.route("/<int:pid>/modifica", methods=["GET", "POST"])
@admin_richiesto
def modifica(pid):
    prodotto = db.get_or_404(Prodotto, pid)
    if request.method == "POST":
        errori = _salva(prodotto)
        if not errori:
            db.session.commit()
            flash("Prodotto aggiornato.", "success")
            return redirect(url_for("prodotti.index"))
        for e in errori:
            flash(e, "danger")
    return render_template("prodotti/form.html", prodotto=prodotto, nuovo=False, riga=None,
                           unita=Unita.query.order_by(Unita.nome).all(), categorie=_categorie())


# ---------------------------------------------------------------- unità di misura

@bp.route("/unita", methods=["GET", "POST"])
@admin_richiesto
def unita():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        simbolo = request.form.get("simbolo", "").strip()
        if not nome or not simbolo:
            flash("Nome e simbolo sono obbligatori.", "danger")
        elif Unita.query.filter(func.lower(Unita.nome) == nome.lower()).first():
            flash("Esiste già un'unità con questo nome.", "danger")
        else:
            db.session.add(Unita(nome=nome[:50], simbolo=simbolo[:15]))
            db.session.commit()
            flash("Unità aggiunta.", "success")
        return redirect(url_for("prodotti.unita"))

    elenco = Unita.query.order_by(Unita.nome).all()
    in_uso = {u.id for u in elenco if Prodotto.query.filter_by(unita_id=u.id).first()
              or RigaOrdine.query.filter_by(unita_id=u.id).first()}
    return render_template("prodotti/unita.html", elenco=elenco, in_uso=in_uso)


@bp.route("/unita/<int:uid>/elimina", methods=["POST"])
@admin_richiesto
def elimina_unita(uid):
    u = db.get_or_404(Unita, uid)
    if Prodotto.query.filter_by(unita_id=uid).first() or RigaOrdine.query.filter_by(unita_id=uid).first():
        flash("Unità in uso: non può essere eliminata.", "danger")
    else:
        db.session.delete(u)
        db.session.commit()
        flash("Unità eliminata.", "success")
    return redirect(url_for("prodotti.unita"))
