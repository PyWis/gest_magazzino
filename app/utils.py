import math
import re
import secrets
from functools import wraps

from flask import abort, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from .models import Ordine, Ruolo, StatoOrdine, StatoSpesa

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN = 8


# ---------------------------------------------------------------- permessi

def ruolo_richiesto(*ruoli):
    def decoratore(f):
        @wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user.ruolo not in ruoli:
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decoratore


admin_richiesto = ruolo_richiesto(Ruolo.SUPERADMIN, Ruolo.ADMIN)
docente_richiesto = ruolo_richiesto(Ruolo.DOCENTE)


# ---------------------------------------------------------------- validazione

def parse_qta(valore):
    """Converte '1,5' / '1.5' / '1.234,5' in float. None se non valido."""
    if valore is None:
        return None
    s = str(valore).strip().replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, 3)


def valida_email(email):
    return bool(EMAIL_RE.match(email or "")) and len(email) <= 255


def valida_password(pw, pw2):
    if len(pw) < PASSWORD_MIN:
        return f"La password deve avere almeno {PASSWORD_MIN} caratteri."
    if pw != pw2:
        return "Le due password non coincidono."
    return None


# ---------------------------------------------------------------- formattazione

def fmt_qta(v):
    if v is None:
        return ""
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    if s == "-0":
        s = "0"
    return s.replace(".", ",")


def fmt_euro(v):
    if v is None:
        return "—"
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def fmt_data(d, ore=True):
    if not d:
        return ""
    return d.strftime("%d/%m/%Y %H:%M" if ore else "%d/%m/%Y")


# ---------------------------------------------------------------- registrazione

def init_utils(app):
    @app.before_request
    def protezione_csrf():
        if request.method == "POST":
            token = session.get("_csrf")
            inviato = request.form.get("_csrf", "")
            if not token or not secrets.compare_digest(token, inviato):
                abort(400, "Sessione scaduta o richiesta non valida. Ricarica la pagina e riprova.")

    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_urlsafe(32)
        return session["_csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def forza_primo_accesso():
        if (current_user.is_authenticated and current_user.primo_accesso
                and request.endpoint not in ("auth.primo_accesso", "auth.logout", "static")):
            return redirect(url_for("auth.primo_accesso"))

    app.add_template_filter(fmt_qta, "qta")
    app.add_template_filter(fmt_euro, "euro")
    app.add_template_filter(fmt_data, "data")

    @app.context_processor
    def variabili_globali():
        ctx = {"Ruolo": Ruolo, "StatoOrdine": StatoOrdine, "StatoSpesa": StatoSpesa}
        if current_user.is_authenticated and current_user.is_admin:
            ctx["n_ordini_in_attesa"] = Ordine.query.filter(
                Ordine.stato.in_(StatoOrdine.APERTI)).count()
        return ctx

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    def errore(e):
        messaggi = {403: "Non hai i permessi per accedere a questa pagina.",
                    404: "Pagina non trovata."}
        msg = messaggi.get(e.code) or e.description
        return render_template("errore.html", codice=e.code, messaggio=msg), e.code
