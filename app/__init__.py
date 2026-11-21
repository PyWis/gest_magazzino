import os
import secrets

import click
from flask import Flask
from flask_login import LoginManager

from .models import UNITA_PREDEFINITE, Ruolo, Unita, Utente, db

SUPERADMIN_EMAIL_DEFAULT = "admin@admin.test"
SUPERADMIN_PASSWORD_DEFAULT = "admin"

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Effettua l'accesso per continuare."
login_manager.login_message_category = "warning"


@login_manager.user_loader
def carica_utente(user_id):
    return db.session.get(Utente, int(user_id))


def _secret_key(instance_path):
    """Usa SECRET_KEY dall'ambiente, altrimenti ne genera una e la salva in instance/."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    percorso = os.path.join(instance_path, "secret_key")
    if not os.path.exists(percorso):
        with open(percorso, "w") as f:
            f.write(secrets.token_hex(32))
    with open(percorso) as f:
        return f.read().strip()


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
    )
    if config:
        app.config.update(config)

    db.init_app(app)
    login_manager.init_app(app)

    from .utils import init_utils
    init_utils(app)

    from .routes import auth, main, ordini, prodotti, spesa, utenti
    for modulo in (auth, main, utenti, prodotti, ordini, spesa):
        app.register_blueprint(modulo.bp)

    with app.app_context():
        db.create_all()
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


def _dati_iniziali():
    if not Utente.query.filter_by(ruolo=Ruolo.SUPERADMIN).first():
        su = Utente(email=SUPERADMIN_EMAIL_DEFAULT, nome="Super", cognome="Admin",
                    ruolo=Ruolo.SUPERADMIN, primo_accesso=True)
        su.set_password(SUPERADMIN_PASSWORD_DEFAULT)
        db.session.add(su)
    if Unita.query.count() == 0:
        for nome, simbolo in UNITA_PREDEFINITE:
            db.session.add(Unita(nome=nome, simbolo=simbolo))
    db.session.commit()
