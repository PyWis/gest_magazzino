import os
import secrets
import warnings

import click
from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate, stamp, upgrade
from sqlalchemy import exc as sa_exc
from sqlalchemy import inspect
from werkzeug.middleware.proxy_fix import ProxyFix

from .models import UNITA_PREDEFINITE, Ruolo, Unita, Utente, db

SUPERADMIN_EMAIL_DEFAULT = "admin@admin.test"
SUPERADMIN_PASSWORD_DEFAULT = "admin"
CARTELLA_MIGRAZIONI = os.path.join(os.path.dirname(__file__), "migrations")

# SQLite non ha un tipo decimale nativo: SQLAlchemy lo segnala, ma i valori vengono
# comunque riletti e arrotondati a 3 decimali, quindi l'avviso non serve.
warnings.filterwarnings("ignore", r".*does \*not\* support Decimal objects natively",
                        category=sa_exc.SAWarning)

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Effettua l'accesso per continuare."
login_manager.login_message_category = "warning"
migrate = Migrate()


@login_manager.user_loader
def carica_utente(user_id):
    return db.session.get(Utente, int(user_id))


def _secret_key(instance_path):
    """Usa SECRET_KEY dall'ambiente, altrimenti ne genera una e la salva in instance/."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    percorso = os.path.join(instance_path, "secret_key")
    if not os.path.exists(percorso):
        fd = os.open(percorso, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    with open(percorso) as f:
        return f.read().strip()


def _env_bool(nome):
    return os.environ.get(nome, "").lower() in ("1", "true", "si", "sì", "yes")


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    app.config.update(
        SECRET_KEY=_secret_key(app.instance_path),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "magazzino.db")),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Da attivare quando il sito è servito in HTTPS: il cookie di sessione viaggia solo cifrato
        SESSION_COOKIE_SECURE=_env_bool("COOKIE_SICURI"),
        NOME_SCUOLA=os.environ.get("NOME_SCUOLA", "Gestionale Magazzino"),
        # Email (facoltative): se MAIL_SERVER è vuoto le notifiche sono disattivate
        MAIL_SERVER=os.environ.get("MAIL_SERVER", ""),
        MAIL_PORT=int(os.environ.get("MAIL_PORT", "587")),
        MAIL_USERNAME=os.environ.get("MAIL_USERNAME", ""),
        MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD", ""),
        MAIL_USE_TLS=_env_bool("MAIL_USE_TLS") or "MAIL_USE_TLS" not in os.environ,
        MAIL_USE_SSL=_env_bool("MAIL_USE_SSL"),
        MAIL_FROM=os.environ.get("MAIL_FROM", ""),
    )
    if config:
        app.config.update(config)

    # Dietro un proxy (nginx su VPS, PythonAnywhere...) l'IP vero del visitatore arriva
    # nell'intestazione X-Forwarded-For: senza questo tutti sembrerebbero avere lo stesso IP
    # e il blocco dopo troppi tentativi di login bloccherebbe l'intera scuola.
    proxy = int(app.config.get("TRUST_PROXY") or os.environ.get("TRUST_PROXY") or 0)
    app.config["TRUST_PROXY"] = proxy
    if proxy:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy, x_proto=proxy, x_host=proxy)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db, directory=CARTELLA_MIGRAZIONI, render_as_batch=True)

    from .utils import init_utils
    init_utils(app)

    from .routes import auth, main, ordini, prodotti, spesa, utenti
    for modulo in (auth, main, utenti, prodotti, ordini, spesa):
        app.register_blueprint(modulo.bp)

    with app.app_context():
        _aggiorna_database()
        _dati_iniziali()

    @app.cli.command("reset-superadmin")
    def reset_superadmin():
        """Riporta il superadmin alle credenziali di default (admin@admin.test / admin)."""
        su = Utente.query.filter_by(ruolo=Ruolo.SUPERADMIN).first()
        altro = Utente.query.filter_by(email=SUPERADMIN_EMAIL_DEFAULT).first()
        if altro and altro is not su:
            raise click.ClickException(f"L'email {SUPERADMIN_EMAIL_DEFAULT} è usata da un altro utente.")
        su.email = SUPERADMIN_EMAIL_DEFAULT
        su.set_password(SUPERADMIN_PASSWORD_DEFAULT)
        su.primo_accesso = True
        su.attivo = True
        db.session.commit()
        click.echo("Superadmin ripristinato: admin@admin.test / admin (cambio obbligatorio al primo accesso).")

    return app


def _aggiorna_database():
    """Crea o aggiorna lo schema all'ultima versione. Un database creato con la prima
    versione del programma (senza storico delle migrazioni) viene riconosciuto e aggiornato."""
    tabelle = inspect(db.engine).get_table_names()
    if "utenti" in tabelle and "alembic_version" not in tabelle:
        stamp(directory=CARTELLA_MIGRAZIONI, revision="0001")
    upgrade(directory=CARTELLA_MIGRAZIONI)


def _dati_iniziali():
    if not Utente.query.filter_by(ruolo=Ruolo.SUPERADMIN).first():
        su = Utente(email=SUPERADMIN_EMAIL_DEFAULT, nome="Super", cognome="Admin",
                    ruolo=Ruolo.SUPERADMIN, primo_accesso=True)
        su.set_password(SUPERADMIN_PASSWORD_DEFAULT)
        db.session.add(su)
    if Unita.query.count() == 0:
        for nome, simbolo, gruppo, fattore in UNITA_PREDEFINITE:
            db.session.add(Unita(nome=nome, simbolo=simbolo, gruppo=gruppo, fattore=fattore))
    db.session.commit()
