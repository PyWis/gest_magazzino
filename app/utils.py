import csv
import io
import logging
import re
import secrets
import smtplib
import threading
import time
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation
from email.message import EmailMessage
from functools import wraps

from flask import (Response, abort, current_app, redirect, render_template, request, session,
                   url_for)
from flask_login import current_user, login_required

from .models import Ordine, Ruolo, StatoOrdine, StatoSpesa, TipoMovimento

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN = 8
PER_PAGINA = 25

log = logging.getLogger(__name__)


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

def parse_qta(valore, decimali=3):
    """Converte '1,5' / '1.5' / '1.234,5' in Decimal. None se non valido."""
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
        v = Decimal(s)
    except InvalidOperation:
        return None
    if not v.is_finite() or abs(v) >= Decimal("1e10"):
        return None
    return v.quantize(Decimal(1).scaleb(-decimali))


def valida_email(email):
    return bool(EMAIL_RE.match(email or "")) and len(email) <= 255


def valida_password(pw, pw2):
    if len(pw) < PASSWORD_MIN:
        return f"La password deve avere almeno {PASSWORD_MIN} caratteri."
    if pw != pw2:
        return "Le due password non coincidono."
    return None


# ---------------------------------------------------------------- protezione login

def ip_client():
    """IP del visitatore. Dietro un proxy fidato (TRUST_PROXY) usa X-Real-IP se presente
    (es. PythonAnywhere); altrimenti l'IP già corretto da ProxyFix tramite X-Forwarded-For."""
    if current_app.config.get("TRUST_PROXY") and request.headers.get("X-Real-IP"):
        return request.headers["X-Real-IP"].strip()
    return request.remote_addr

class LimitatoreLogin:
    """Blocca un indirizzo IP / email dopo troppi tentativi falliti (in memoria)."""

    def __init__(self, max_tentativi=5, finestra=15 * 60):
        self.max, self.finestra = max_tentativi, finestra
        self._falliti = defaultdict(deque)
        self._lock = threading.Lock()

    def _pulisci(self, chiave, ora):
        dq = self._falliti[chiave]
        while dq and ora - dq[0] > self.finestra:
            dq.popleft()
        return dq

    def bloccato(self, *chiavi):
        """Secondi di attesa rimanenti (0 se non bloccato)."""
        ora = time.monotonic()
        with self._lock:
            attesa = 0
            for k in chiavi:
                dq = self._pulisci(k, ora)
                if len(dq) >= self.max:
                    attesa = max(attesa, int(self.finestra - (ora - dq[0])) + 1)
            return attesa

    def fallito(self, *chiavi):
        ora = time.monotonic()
        with self._lock:
            for k in chiavi:
                self._pulisci(k, ora).append(ora)

    def reset(self, *chiavi):
        with self._lock:
            for k in chiavi:
                self._falliti.pop(k, None)


limitatore_login = LimitatoreLogin()


# ---------------------------------------------------------------- email

def invia_email(destinatario, oggetto, testo):
    """Invia un'email in background. Non fa nulla se MAIL_SERVER non è configurato."""
    cfg = current_app.config
    if not cfg.get("MAIL_SERVER") or not destinatario:
        return False
    msg = EmailMessage()
    msg["From"] = cfg.get("MAIL_FROM") or cfg.get("MAIL_USERNAME") or "magazzino@localhost"
    msg["To"] = destinatario
    msg["Subject"] = oggetto
    msg.set_content(testo)
    impostazioni = {k: cfg.get(k) for k in ("MAIL_SERVER", "MAIL_PORT", "MAIL_USERNAME",
                                            "MAIL_PASSWORD", "MAIL_USE_TLS", "MAIL_USE_SSL")}
    if cfg.get("TESTING"):
        current_app.extensions.setdefault("email_inviate", []).append(msg)
        return True

    def _invia():
        try:
            classe = smtplib.SMTP_SSL if impostazioni["MAIL_USE_SSL"] else smtplib.SMTP
            with classe(impostazioni["MAIL_SERVER"], int(impostazioni["MAIL_PORT"] or 25), timeout=20) as s:
                if impostazioni["MAIL_USE_TLS"] and not impostazioni["MAIL_USE_SSL"]:
                    s.starttls()
                if impostazioni["MAIL_USERNAME"]:
                    s.login(impostazioni["MAIL_USERNAME"], impostazioni["MAIL_PASSWORD"] or "")
                s.send_message(msg)
        except Exception:  # un problema di posta non deve bloccare il gestionale
            log.exception("Invio email a %s non riuscito", destinatario)

    threading.Thread(target=_invia, daemon=True).start()
    return True


def notifica_docente(ordine):
    d = ordine.docente
    if not d.notifiche_email or not d.attivo:
        return
    link = url_for("ordini.dettaglio", oid=ordine.id, _external=True)
    righe = "\n".join(f"  • {r.nome}: consegnati {fmt_qta(r.quantita_evasa)} su "
                      f"{fmt_qta(r.quantita_richiesta)} {r.unita.simbolo}" for r in ordine.righe)
    nota = f"\nNota del magazzino: {ordine.nota_admin}\n" if ordine.nota_admin else ""
    invia_email(d.email, f"Ordine #{ordine.id}: {ordine.stato_label.lower()}",
                f"Ciao {d.nome or d.nome_completo},\n\nil tuo ordine #{ordine.id} è ora "
                f"«{ordine.stato_label}».\n\n{righe}\n{nota}\nDettagli: {link}\n\n"
                f"— {current_app.config['NOME_SCUOLA']} · Magazzino")


# ---------------------------------------------------------------- formattazione

def fmt_qta(v):
    if v is None:
        return ""
    s = f"{Decimal(str(v)):.3f}".rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s.replace(".", ",")


def fmt_euro(v):
    if v is None:
        return "—"
    s = f"{Decimal(str(v)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def fmt_data(d, ore=True):
    if not d:
        return ""
    return d.strftime("%d/%m/%Y %H:%M" if ore else "%d/%m/%Y")


def fmt_tempo_fa(d):
    """'oggi', 'ieri', '3 giorni fa'..."""
    if not d:
        return ""
    from .models import adesso
    giorni = (adesso().date() - d.date()).days
    if giorni <= 0:
        return "oggi"
    if giorni == 1:
        return "ieri"
    return f"{giorni} giorni fa"


def csv_response(nome_file, intestazioni, righe):
    """CSV con separatore ';' e BOM: si apre direttamente in Excel italiano."""
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";")
    w.writerow(intestazioni)
    for r in righe:
        w.writerow(["" if c is None else c for c in r])
    return Response(buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome_file}"'})


def pagina():
    try:
        return max(1, int(request.args.get("pagina", 1)))
    except ValueError:
        return 1


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
    app.add_template_filter(fmt_tempo_fa, "tempo_fa")

    def url_pagina(n):
        args = dict(request.view_args or {})
        args.update(request.args.to_dict())
        args["pagina"] = n
        return url_for(request.endpoint, **args)

    app.jinja_env.globals["url_pagina"] = url_pagina

    @app.context_processor
    def variabili_globali():
        ctx = {"Ruolo": Ruolo, "StatoOrdine": StatoOrdine, "StatoSpesa": StatoSpesa,
               "TipoMovimento": TipoMovimento, "NOME_SCUOLA": app.config["NOME_SCUOLA"]}
        if current_user.is_authenticated and current_user.is_admin:
            ctx["n_ordini_in_attesa"] = Ordine.query.filter(
                Ordine.stato.in_(StatoOrdine.APERTI)).count()
        return ctx

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(429)
    def errore(e):
        messaggi = {403: "Non hai i permessi per accedere a questa pagina.",
                    404: "Pagina non trovata.",
                    405: "Operazione non consentita."}
        msg = messaggi.get(e.code) or e.description
        return render_template("errore.html", codice=e.code, messaggio=msg), e.code

    @app.errorhandler(500)
    def errore_interno(e):
        from .models import db
        db.session.rollback()
        return render_template("errore.html", codice=500,
                               messaggio="Si è verificato un errore imprevisto. Nessuna modifica è "
                                         "stata salvata: riprova, e se il problema continua "
                                         "avvisa l'amministratore."), 500
