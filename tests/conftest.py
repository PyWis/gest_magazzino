import re

import pytest

from app import create_app
from app.models import Prodotto, Ruolo, Unita, Utente, db
from app.utils import limitatore_login


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
                      "MAIL_SERVER": "smtp.test", "SERVER_NAME": "magazzino.test"})
    limitatore_login._falliti.clear()
    with app.app_context():
        su = Utente.query.filter_by(ruolo=Ruolo.SUPERADMIN).first()
        su.primo_accesso = False
        su.email, su.nome, su.cognome = "admin@scuola.it", "Anna", "Admin"
        su.set_password("password-admin")
        doc = Utente(email="doc@scuola.it", nome="Dario", cognome="Docente", ruolo=Ruolo.DOCENTE,
                     primo_accesso=False)
        doc.set_password("password-doc")
        db.session.add(doc)
        db.session.commit()
    yield app


@pytest.fixture
def unita(app):
    with app.app_context():
        return {u.simbolo: u.id for u in Unita.query}


class Client:
    """Client di test che gestisce da solo il token CSRF."""

    def __init__(self, app):
        self.c = app.test_client()
        self.token = None

    def _aggiorna_token(self, html):
        m = re.search(r'name="_csrf" value="([^"]+)"', html)
        if m:
            self.token = m.group(1)

    def get(self, url, **kw):
        r = self.c.get(url, **kw)
        if r.mimetype == "text/html":
            self._aggiorna_token(r.get_data(as_text=True))
        return r

    def post(self, url, data=None, **kw):
        if self.token is None:
            self.get("/login")
        data = dict(data or {})
        data.setdefault("_csrf", self.token)
        r = self.c.post(url, data=data, **kw)
        if r.mimetype == "text/html":
            self._aggiorna_token(r.get_data(as_text=True))
        return r

    def login(self, email, password):
        self.get("/login")
        r = self.post("/login", {"email": email, "password": password})
        self.get("/", follow_redirects=True)
        return r


@pytest.fixture
def admin(app):
    c = Client(app)
    c.login("admin@scuola.it", "password-admin")
    return c


@pytest.fixture
def docente(app):
    c = Client(app)
    c.login("doc@scuola.it", "password-doc")
    return c


def crea_prodotto(app, nome, simbolo, giacenza="0", scorta="0"):
    from app.magazzino import muovi
    from app.models import TipoMovimento
    with app.app_context():
        u = Unita.query.filter_by(simbolo=simbolo).one()
        p = Prodotto(nome=nome, unita=u, giacenza=0, scorta_minima=scorta)
        db.session.add(p)
        db.session.flush()
        if float(giacenza):
            muovi(p, giacenza, TipoMovimento.INIZIALE)
        db.session.commit()
        return p.id
