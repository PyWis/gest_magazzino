from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..models import Ruolo, Utente, db
from ..utils import admin_richiesto, valida_email, valida_password

bp = Blueprint("utenti", __name__, url_prefix="/utenti")


def ruoli_assegnabili():
    """Il superadmin crea admin e docenti; gli admin solo docenti."""
    if current_user.is_superadmin:
        return [Ruolo.ADMIN, Ruolo.DOCENTE]
    return [Ruolo.DOCENTE]


def puo_gestire(utente):
    if utente.id == current_user.id or utente.is_superadmin:
        return False
    return current_user.is_superadmin or utente.is_docente


@bp.route("/")
@admin_richiesto
def index():
    query = Utente.query
    if not current_user.is_superadmin:
        query = query.filter_by(ruolo=Ruolo.DOCENTE)
    utenti = query.order_by(Utente.ruolo.desc(), Utente.cognome, Utente.nome).all()
    return render_template("utenti/index.html", utenti=utenti, puo_gestire=puo_gestire)


def _leggi_form(utente, nuovo):
    errori = []
    nome = request.form.get("nome", "").strip()
    cognome = request.form.get("cognome", "").strip()
    email = request.form.get("email", "").strip().lower()
    ruolo = request.form.get("ruolo", Ruolo.DOCENTE)
    password = request.form.get("password", "")
    password2 = request.form.get("password2", "")

    if not nome or not cognome:
        errori.append("Nome e cognome sono obbligatori.")
    if not valida_email(email):
        errori.append("Inserisci un indirizzo email valido.")
    elif Utente.query.filter(Utente.email == email, Utente.id != (utente.id or 0)).first():
        errori.append("Esiste già un utente con questa email.")
    if ruolo not in ruoli_assegnabili():
        errori.append("Ruolo non consentito.")
    if nuovo or password:
        err = valida_password(password, password2)
        if err:
            errori.append(err)

    if not errori:
        utente.nome, utente.cognome, utente.email, utente.ruolo = nome, cognome, email, ruolo
        if not nuovo:
            utente.attivo = request.form.get("attivo") == "1"
        if password:
            utente.set_password(password)
            utente.primo_accesso = True  # al prossimo accesso dovrà sceglierne una sua
    return errori


@bp.route("/nuovo", methods=["GET", "POST"])
@admin_richiesto
def nuovo():
    utente = Utente(ruolo=request.args.get("ruolo", Ruolo.DOCENTE))
    if request.method == "POST":
        errori = _leggi_form(utente, nuovo=True)
        if not errori:
            db.session.add(utente)
            db.session.commit()
            flash(f"Utente {utente.nome_completo} creato. Dovrà cambiare la password al primo accesso.",
                  "success")
            return redirect(url_for("utenti.index"))
        for e in errori:
            flash(e, "danger")
    return render_template("utenti/form.html", utente=utente, nuovo=True,
                           ruoli=ruoli_assegnabili())


@bp.route("/<int:uid>/modifica", methods=["GET", "POST"])
@admin_richiesto
def modifica(uid):
    utente = db.get_or_404(Utente, uid)
    if not puo_gestire(utente):
        abort(403)
    if request.method == "POST":
        errori = _leggi_form(utente, nuovo=False)
        if not errori:
            db.session.commit()
            flash("Utente aggiornato.", "success")
            return redirect(url_for("utenti.index"))
        db.session.rollback()
        for e in errori:
            flash(e, "danger")
    return render_template("utenti/form.html", utente=utente, nuovo=False,
                           ruoli=ruoli_assegnabili())
