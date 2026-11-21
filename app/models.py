from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

EPS = 1e-9  # tolleranza per confronti tra quantità decimali


def adesso():
    return datetime.now()


# ---------------------------------------------------------------- utenti

class Ruolo:
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    DOCENTE = "docente"
    ETICHETTE = {SUPERADMIN: "Superadmin", ADMIN: "Admin", DOCENTE: "Docente"}


class Utente(UserMixin, db.Model):
    __tablename__ = "utenti"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    nome = db.Column(db.String(100), nullable=False, default="")
    cognome = db.Column(db.String(100), nullable=False, default="")
    password_hash = db.Column(db.String(255), nullable=False)
    ruolo = db.Column(db.String(20), nullable=False, default=Ruolo.DOCENTE)
    attivo = db.Column(db.Boolean, nullable=False, default=True)
    # True finché l'utente non sceglie le proprie credenziali
    primo_accesso = db.Column(db.Boolean, nullable=False, default=True)
    creato_il = db.Column(db.DateTime, nullable=False, default=adesso)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):  # usato da Flask-Login
        return self.attivo

    @property
    def is_superadmin(self):
        return self.ruolo == Ruolo.SUPERADMIN

    @property
    def is_admin(self):
        """Admin o superadmin: possono gestire magazzino e ordini."""
        return self.ruolo in (Ruolo.SUPERADMIN, Ruolo.ADMIN)

    @property
    def is_docente(self):
        return self.ruolo == Ruolo.DOCENTE

    @property
    def nome_completo(self):
        n = f"{self.nome} {self.cognome}".strip()
        return n or self.email

    @property
    def ruolo_label(self):
        return Ruolo.ETICHETTE.get(self.ruolo, self.ruolo)


# ---------------------------------------------------------------- magazzino

class Unita(db.Model):
    """Unità di misura merceologica (litri, kg, cm, pezzi...)."""
    __tablename__ = "unita"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True, nullable=False)
    simbolo = db.Column(db.String(15), nullable=False)

    def __str__(self):
        return f"{self.nome} ({self.simbolo})"


UNITA_PREDEFINITE = [
    ("Pezzi", "pz"),
    ("Confezioni", "conf"),
    ("Litri", "l"),
    ("Millilitri", "ml"),
    ("Chilogrammi", "kg"),
    ("Grammi", "g"),
    ("Metri", "m"),
    ("Centimetri", "cm"),
    ("Metri quadrati", "m²"),
]


class Prodotto(db.Model):
    __tablename__ = "prodotti"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    descrizione = db.Column(db.Text, nullable=False, default="")
    categoria = db.Column(db.String(100), nullable=False, default="")
    unita_id = db.Column(db.Integer, db.ForeignKey("unita.id"), nullable=False)
    giacenza = db.Column(db.Float, nullable=False, default=0)
    scorta_minima = db.Column(db.Float, nullable=False, default=0)
    attivo = db.Column(db.Boolean, nullable=False, default=True)
    creato_il = db.Column(db.DateTime, nullable=False, default=adesso)

    unita = db.relationship("Unita")

    @property
    def sotto_scorta(self):
        return self.scorta_minima > 0 and self.giacenza <= self.scorta_minima + EPS


# ---------------------------------------------------------------- ordini dei docenti

class StatoOrdine:
    IN_ATTESA = "in_attesa"
    PARZIALE = "evaso_parziale"
    EVASO = "evaso"
    CHIUSO = "chiuso"
    RIFIUTATO = "rifiutato"
    ANNULLATO = "annullato"

    APERTI = (IN_ATTESA, PARZIALE)
    ETICHETTE = {
        IN_ATTESA: "In attesa",
        PARZIALE: "Evaso in parte",
        EVASO: "Evaso",
        CHIUSO: "Chiuso",
        RIFIUTATO: "Rifiutato",
        ANNULLATO: "Annullato",
    }
    COLORI = {
        IN_ATTESA: "warning",
        PARZIALE: "info",
        EVASO: "success",
        CHIUSO: "secondary",
        RIFIUTATO: "danger",
        ANNULLATO: "dark",
    }


class Ordine(db.Model):
    __tablename__ = "ordini"

    id = db.Column(db.Integer, primary_key=True)
    docente_id = db.Column(db.Integer, db.ForeignKey("utenti.id"), nullable=False)
    stato = db.Column(db.String(20), nullable=False, default=StatoOrdine.IN_ATTESA)
    note = db.Column(db.Text, nullable=False, default="")
    nota_admin = db.Column(db.Text, nullable=False, default="")
    creato_il = db.Column(db.DateTime, nullable=False, default=adesso)
    aggiornato_il = db.Column(db.DateTime, nullable=False, default=adesso, onupdate=adesso)
    gestito_da_id = db.Column(db.Integer, db.ForeignKey("utenti.id"))

    docente = db.relationship("Utente", foreign_keys=[docente_id])
    gestito_da = db.relationship("Utente", foreign_keys=[gestito_da_id])
    righe = db.relationship(
        "RigaOrdine", back_populates="ordine", cascade="all, delete-orphan",
        order_by="RigaOrdine.id",
    )

    @property
    def aperto(self):
        return self.stato in StatoOrdine.APERTI

    @property
    def stato_label(self):
        return StatoOrdine.ETICHETTE.get(self.stato, self.stato)

    @property
    def stato_colore(self):
        return StatoOrdine.COLORI.get(self.stato, "secondary")

    @property
    def qualcosa_consegnato(self):
        return any(r.quantita_evasa > EPS for r in self.righe)

    def aggiorna_stato(self):
        """Ricalcola lo stato in base alle quantità consegnate (solo se aperto)."""
        if not self.aperto:
            return
        if all(r.completa for r in self.righe):
            self.stato = StatoOrdine.EVASO
        elif self.qualcosa_consegnato:
            self.stato = StatoOrdine.PARZIALE
        else:
            self.stato = StatoOrdine.IN_ATTESA


class RigaOrdine(db.Model):
    __tablename__ = "righe_ordine"

    id = db.Column(db.Integer, primary_key=True)
    ordine_id = db.Column(db.Integer, db.ForeignKey("ordini.id"), nullable=False)
    # NULL finché una richiesta "Altro" non viene collegata a un prodotto
    prodotto_id = db.Column(db.Integer, db.ForeignKey("prodotti.id"))
    descrizione_libera = db.Column(db.String(255), nullable=False, default="")
    richiesta_extra = db.Column(db.Boolean, nullable=False, default=False)
    unita_id = db.Column(db.Integer, db.ForeignKey("unita.id"), nullable=False)
    quantita_richiesta = db.Column(db.Float, nullable=False)
    quantita_evasa = db.Column(db.Float, nullable=False, default=0)

    ordine = db.relationship("Ordine", back_populates="righe")
    prodotto = db.relationship("Prodotto")
    unita = db.relationship("Unita")

    @property
    def nome(self):
        return self.prodotto.nome if self.prodotto else self.descrizione_libera

    @property
    def mancante(self):
        return max(0.0, self.quantita_richiesta - self.quantita_evasa)

    @property
    def completa(self):
        return self.mancante <= EPS


# ---------------------------------------------------------------- ordini di spesa

class StatoSpesa:
    BOZZA = "bozza"
    INVIATO = "inviato"
    RICEVUTO = "ricevuto"
    ANNULLATO = "annullato"

    ETICHETTE = {BOZZA: "Bozza", INVIATO: "Inviato al fornitore",
                 RICEVUTO: "Ricevuto", ANNULLATO: "Annullato"}
    COLORI = {BOZZA: "secondary", INVIATO: "primary",
              RICEVUTO: "success", ANNULLATO: "dark"}


class OrdineSpesa(db.Model):
    __tablename__ = "ordini_spesa"

    id = db.Column(db.Integer, primary_key=True)
    fornitore = db.Column(db.String(200), nullable=False, default="")
    note = db.Column(db.Text, nullable=False, default="")
    stato = db.Column(db.String(20), nullable=False, default=StatoSpesa.BOZZA)
    creato_da_id = db.Column(db.Integer, db.ForeignKey("utenti.id"), nullable=False)
    ordine_origine_id = db.Column(db.Integer, db.ForeignKey("ordini.id"))
    creato_il = db.Column(db.DateTime, nullable=False, default=adesso)
    inviato_il = db.Column(db.DateTime)
    ricevuto_il = db.Column(db.DateTime)

    creato_da = db.relationship("Utente")
    ordine_origine = db.relationship("Ordine", backref="ordini_spesa")
    righe = db.relationship(
        "RigaSpesa", back_populates="ordine_spesa", cascade="all, delete-orphan",
        order_by="RigaSpesa.id",
    )

    @property
    def stato_label(self):
        return StatoSpesa.ETICHETTE.get(self.stato, self.stato)

    @property
    def stato_colore(self):
        return StatoSpesa.COLORI.get(self.stato, "secondary")

    @property
    def modificabile(self):
        return self.stato == StatoSpesa.BOZZA

    @property
    def totale(self):
        return sum(r.subtotale or 0 for r in self.righe)


class RigaSpesa(db.Model):
    __tablename__ = "righe_spesa"

    id = db.Column(db.Integer, primary_key=True)
    ordine_spesa_id = db.Column(db.Integer, db.ForeignKey("ordini_spesa.id"), nullable=False)
    prodotto_id = db.Column(db.Integer, db.ForeignKey("prodotti.id"), nullable=False)
    quantita = db.Column(db.Float, nullable=False)
    prezzo_unitario = db.Column(db.Float)  # facoltativo, in euro

    ordine_spesa = db.relationship("OrdineSpesa", back_populates="righe")
    prodotto = db.relationship("Prodotto")

    @property
    def subtotale(self):
        if self.prezzo_unitario is None:
            return None
        return self.quantita * self.prezzo_unitario
