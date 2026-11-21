from datetime import datetime
from decimal import Decimal

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

ZERO = Decimal("0")


def Quantita(**kw):
    """Colonna per le quantità: decimale esatto con 3 cifre dopo la virgola."""
    return db.Column(db.Numeric(14, 3, asdecimal=True), **kw)


def D(v):
    """Converte qualsiasi numero in Decimal arrotondato a 3 decimali."""
    if v is None:
        return None
    if not isinstance(v, Decimal):
        v = Decimal(str(v))
    return v.quantize(Decimal("0.001"))


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
    # Il docente riceve un'email quando il suo ordine cambia stato (se il server email è configurato)
    notifiche_email = db.Column(db.Boolean, nullable=False, default=True)
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
    def iniziali(self):
        i = (self.nome[:1] + self.cognome[:1]).upper()
        return i or self.email[:1].upper()

    @property
    def ruolo_label(self):
        return Ruolo.ETICHETTE.get(self.ruolo, self.ruolo)


# ---------------------------------------------------------------- unità di misura

class GruppoUnita:
    """Unità dello stesso gruppo sono convertibili tra loro tramite `fattore`
    (quante unità base vale 1 unità: base = l, kg, m, m²)."""
    VOLUME = "volume"
    MASSA = "massa"
    LUNGHEZZA = "lunghezza"
    SUPERFICIE = "superficie"
    ETICHETTE = {VOLUME: "Volume (base: litri)", MASSA: "Massa (base: kg)",
                 LUNGHEZZA: "Lunghezza (base: metri)", SUPERFICIE: "Superficie (base: m²)"}


class Unita(db.Model):
    """Unità di misura merceologica (litri, kg, cm, pezzi...)."""
    __tablename__ = "unita"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True, nullable=False)
    simbolo = db.Column(db.String(15), nullable=False)
    gruppo = db.Column(db.String(20), nullable=False, default="")
    fattore = db.Column(db.Numeric(18, 6, asdecimal=True))

    def __str__(self):
        return f"{self.nome} ({self.simbolo})"

    def convertibile_in(self, altra):
        if self.id == altra.id:
            return True
        return bool(self.gruppo) and self.gruppo == altra.gruppo and self.fattore and altra.fattore

    def converti(self, quantita, altra):
        """Converte `quantita` da questa unità in `altra`. None se non convertibile."""
        if self.id == altra.id:
            return D(quantita)
        if not self.convertibile_in(altra):
            return None
        return D(Decimal(quantita) * Decimal(self.fattore) / Decimal(altra.fattore))


# (nome, simbolo, gruppo, fattore rispetto all'unità base)
UNITA_PREDEFINITE = [
    ("Pezzi", "pz", "", None),
    ("Confezioni", "conf", "", None),
    ("Litri", "l", GruppoUnita.VOLUME, "1"),
    ("Millilitri", "ml", GruppoUnita.VOLUME, "0.001"),
    ("Chilogrammi", "kg", GruppoUnita.MASSA, "1"),
    ("Grammi", "g", GruppoUnita.MASSA, "0.001"),
    ("Metri", "m", GruppoUnita.LUNGHEZZA, "1"),
    ("Centimetri", "cm", GruppoUnita.LUNGHEZZA, "0.01"),
    ("Metri quadrati", "m²", GruppoUnita.SUPERFICIE, "1"),
]


# ---------------------------------------------------------------- magazzino

class Prodotto(db.Model):
    __tablename__ = "prodotti"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    descrizione = db.Column(db.Text, nullable=False, default="")
    categoria = db.Column(db.String(100), nullable=False, default="")
    unita_id = db.Column(db.Integer, db.ForeignKey("unita.id"), nullable=False)
    # La giacenza si modifica SOLO tramite movimenti (vedi app/magazzino.py)
    giacenza = Quantita(nullable=False, default=ZERO)
    scorta_minima = Quantita(nullable=False, default=ZERO)
    attivo = db.Column(db.Boolean, nullable=False, default=True)
    creato_il = db.Column(db.DateTime, nullable=False, default=adesso)

    unita = db.relationship("Unita")

    @property
    def sotto_scorta(self):
        return self.scorta_minima > 0 and self.giacenza <= self.scorta_minima

    @property
    def livello(self):
        """Percentuale di riempimento rispetto a 2× la scorta minima (per le barre)."""
        if not self.scorta_minima:
            return 100 if self.giacenza > 0 else 0
        return int(min(100, max(0, self.giacenza / (2 * self.scorta_minima) * 100)))

    @property
    def livello_colore(self):
        if self.giacenza <= 0:
            return "danger"
        if self.sotto_scorta:
            return "warning"
        return "success"


class TipoMovimento:
    CARICO = "carico"        # merce ricevuta da un ordine di spesa
    SCARICO = "scarico"      # consegna a un docente
    RETTIFICA = "rettifica"  # inventario / correzione manuale
    INIZIALE = "iniziale"    # giacenza al momento della creazione del prodotto
    ETICHETTE = {CARICO: "Carico", SCARICO: "Scarico", RETTIFICA: "Rettifica", INIZIALE: "Giacenza iniziale"}
    COLORI = {CARICO: "success", SCARICO: "primary", RETTIFICA: "warning", INIZIALE: "secondary"}
    ICONE = {CARICO: "box-arrow-in-down", SCARICO: "box-arrow-up", RETTIFICA: "sliders", INIZIALE: "flag"}


class Movimento(db.Model):
    """Registro di ogni variazione di giacenza: chi, quando, quanto e perché."""
    __tablename__ = "movimenti"

    id = db.Column(db.Integer, primary_key=True)
    prodotto_id = db.Column(db.Integer, db.ForeignKey("prodotti.id"), nullable=False, index=True)
    tipo = db.Column(db.String(20), nullable=False)
    quantita = Quantita(nullable=False)        # con segno: + entra, - esce
    giacenza_dopo = Quantita(nullable=False)
    nota = db.Column(db.String(255), nullable=False, default="")
    utente_id = db.Column(db.Integer, db.ForeignKey("utenti.id"))
    ordine_id = db.Column(db.Integer, db.ForeignKey("ordini.id"))
    ordine_spesa_id = db.Column(db.Integer, db.ForeignKey("ordini_spesa.id"))
    creato_il = db.Column(db.DateTime, nullable=False, default=adesso, index=True)

    prodotto = db.relationship("Prodotto", backref=db.backref("movimenti", lazy="dynamic"))
    utente = db.relationship("Utente")
    ordine = db.relationship("Ordine")
    ordine_spesa = db.relationship("OrdineSpesa")

    @property
    def tipo_label(self):
        return TipoMovimento.ETICHETTE.get(self.tipo, self.tipo)

    @property
    def tipo_colore(self):
        return TipoMovimento.COLORI.get(self.tipo, "secondary")

    @property
    def tipo_icona(self):
        return TipoMovimento.ICONE.get(self.tipo, "dot")


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
        return any(r.quantita_evasa > 0 for r in self.righe)

    @property
    def righe_complete(self):
        return sum(1 for r in self.righe if r.completa)

    @property
    def percentuale(self):
        if not self.righe:
            return 0
        return int(self.righe_complete * 100 / len(self.righe))

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
    # Quantità e unità come le aveva scritte il docente (es. "500 ml"), se poi convertite
    richiesta_originale = db.Column(db.String(60), nullable=False, default="")
    unita_id = db.Column(db.Integer, db.ForeignKey("unita.id"), nullable=False)
    quantita_richiesta = Quantita(nullable=False)
    quantita_evasa = Quantita(nullable=False, default=ZERO)

    ordine = db.relationship("Ordine", back_populates="righe")
    prodotto = db.relationship("Prodotto")
    unita = db.relationship("Unita")

    @property
    def nome(self):
        return self.prodotto.nome if self.prodotto else self.descrizione_libera

    @property
    def mancante(self):
        return max(ZERO, self.quantita_richiesta - (self.quantita_evasa or ZERO))

    @property
    def completa(self):
        return self.mancante <= 0


# ---------------------------------------------------------------- ordini di spesa

class Fornitore(db.Model):
    __tablename__ = "fornitori"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), unique=True, nullable=False)
    email = db.Column(db.String(255), nullable=False, default="")
    telefono = db.Column(db.String(50), nullable=False, default="")
    note = db.Column(db.Text, nullable=False, default="")
    attivo = db.Column(db.Boolean, nullable=False, default=True)


class StatoSpesa:
    BOZZA = "bozza"
    INVIATO = "inviato"
    PARZIALE = "ricevuto_parziale"
    RICEVUTO = "ricevuto"
    ANNULLATO = "annullato"

    # Ordini di spesa la cui merce è "in arrivo" (conta per non riordinare due volte)
    APERTI = (BOZZA, INVIATO, PARZIALE)
    ETICHETTE = {BOZZA: "Bozza", INVIATO: "Inviato al fornitore", PARZIALE: "Ricevuto in parte",
                 RICEVUTO: "Ricevuto", ANNULLATO: "Annullato"}
    COLORI = {BOZZA: "secondary", INVIATO: "primary", PARZIALE: "info",
              RICEVUTO: "success", ANNULLATO: "dark"}


class OrdineSpesa(db.Model):
    __tablename__ = "ordini_spesa"

    id = db.Column(db.Integer, primary_key=True)
    fornitore_id = db.Column(db.Integer, db.ForeignKey("fornitori.id"))
    fornitore_testo = db.Column("fornitore", db.String(200), nullable=False, default="")  # storico
    note = db.Column(db.Text, nullable=False, default="")
    stato = db.Column(db.String(20), nullable=False, default=StatoSpesa.BOZZA)
    creato_da_id = db.Column(db.Integer, db.ForeignKey("utenti.id"), nullable=False)
    ordine_origine_id = db.Column(db.Integer, db.ForeignKey("ordini.id"))
    creato_il = db.Column(db.DateTime, nullable=False, default=adesso)
    inviato_il = db.Column(db.DateTime)
    ricevuto_il = db.Column(db.DateTime)

    fornitore = db.relationship("Fornitore", backref="ordini_spesa")
    creato_da = db.relationship("Utente")
    ordine_origine = db.relationship("Ordine", backref="ordini_spesa")
    righe = db.relationship(
        "RigaSpesa", back_populates="ordine_spesa", cascade="all, delete-orphan",
        order_by="RigaSpesa.id",
    )

    @property
    def fornitore_nome(self):
        return self.fornitore.nome if self.fornitore else self.fornitore_testo

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
    def aperto(self):
        return self.stato in StatoSpesa.APERTI

    @property
    def ricevibile(self):
        return self.stato in StatoSpesa.APERTI

    @property
    def totale(self):
        return sum((r.subtotale or ZERO for r in self.righe), ZERO)


class RigaSpesa(db.Model):
    __tablename__ = "righe_spesa"

    id = db.Column(db.Integer, primary_key=True)
    ordine_spesa_id = db.Column(db.Integer, db.ForeignKey("ordini_spesa.id"), nullable=False)
    prodotto_id = db.Column(db.Integer, db.ForeignKey("prodotti.id"), nullable=False)
    quantita = Quantita(nullable=False)
    quantita_ricevuta = Quantita(nullable=False, default=ZERO)
    prezzo_unitario = db.Column(db.Numeric(12, 2, asdecimal=True))  # facoltativo, in euro

    ordine_spesa = db.relationship("OrdineSpesa", back_populates="righe")
    prodotto = db.relationship("Prodotto")

    @property
    def da_ricevere(self):
        return max(ZERO, self.quantita - (self.quantita_ricevuta or ZERO))

    @property
    def subtotale(self):
        if self.prezzo_unitario is None:
            return None
        return self.quantita * self.prezzo_unitario
