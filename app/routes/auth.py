from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .. import SUPERADMIN_EMAIL_DEFAULT, SUPERADMIN_PASSWORD_DEFAULT
from ..models import Utente, db
from ..utils import ip_client, limitatore_login, valida_email, valida_password

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        chiavi = (f"ip:{ip_client()}", f"email:{email}")
        attesa = limitatore_login.bloccato(*chiavi)
        if attesa:
            flash(f"Troppi tentativi falliti. Riprova tra {max(1, attesa // 60)} minuti.", "danger")
            return render_template("auth/login.html"), 429
        utente = Utente.query.filter_by(email=email).first()
        if utente and utente.check_password(password):
            if not utente.attivo:
                flash("Il tuo account è disattivato. Contatta un amministratore.", "danger")
            else:
                limitatore_login.reset(*chiavi)
                session.pop("_csrf", None)
                login_user(utente)
                prossima = request.args.get("next", "")
                if not prossima.startswith("/") or prossima.startswith("//"):
                    prossima = url_for("main.home")
                return redirect(prossima)
        else:
            limitatore_login.fallito(*chiavi)
            flash("Email o password non corretti.", "danger")
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    flash("Sei uscito.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/primo-accesso", methods=["GET", "POST"])
@login_required
def primo_accesso():
    """Al primo accesso: il superadmin sceglie email e password, gli altri la password."""
    if not current_user.primo_accesso:
        return redirect(url_for("main.home"))
    chiedi_email = current_user.is_superadmin

    if request.method == "POST":
        errori = []
        pw = request.form.get("password", "")
        pw2 = request.form.get("password2", "")
        err = valida_password(pw, pw2)
        if err:
            errori.append(err)
        elif pw == SUPERADMIN_PASSWORD_DEFAULT or current_user.check_password(pw):
            errori.append("Scegli una password diversa da quella attuale.")

        if chiedi_email:
            email = request.form.get("email", "").strip().lower()
            if not valida_email(email):
                errori.append("Inserisci un indirizzo email valido.")
            elif email == SUPERADMIN_EMAIL_DEFAULT:
                errori.append("Scegli un'email diversa da quella predefinita.")
            elif Utente.query.filter(Utente.email == email, Utente.id != current_user.id).first():
                errori.append("Questa email è già usata da un altro utente.")

        if not errori:
            if chiedi_email:
                current_user.email = email
            current_user.set_password(pw)
            current_user.primo_accesso = False
            db.session.commit()
            flash("Credenziali aggiornate. Benvenuto!", "success")
            return redirect(url_for("main.home"))
        for e in errori:
            flash(e, "danger")

    return render_template("auth/primo_accesso.html", chiedi_email=chiedi_email)


@bp.route("/profilo", methods=["GET", "POST"])
@login_required
def profilo():
    if request.method == "POST" and request.form.get("azione") == "notifiche":
        current_user.notifiche_email = request.form.get("notifiche_email") == "1"
        db.session.commit()
        flash("Preferenze salvate.", "success")
        return redirect(url_for("auth.profilo"))
    if request.method == "POST":
        attuale = request.form.get("password_attuale", "")
        pw = request.form.get("password", "")
        pw2 = request.form.get("password2", "")
        if not current_user.check_password(attuale):
            flash("La password attuale non è corretta.", "danger")
        elif (err := valida_password(pw, pw2)):
            flash(err, "danger")
        else:
            current_user.set_password(pw)
            db.session.commit()
            flash("Password aggiornata.", "success")
            return redirect(url_for("auth.profilo"))
    return render_template("auth/profilo.html", email_attive=bool(current_app.config["MAIL_SERVER"]))
