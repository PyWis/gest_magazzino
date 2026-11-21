"""Schema iniziale (prima versione del gestionale)

Revision ID: 0001
Revises:
Create Date: 2026-11-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "utenti",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("nome", sa.String(100), nullable=False),
        sa.Column("cognome", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("ruolo", sa.String(20), nullable=False),
        sa.Column("attivo", sa.Boolean, nullable=False),
        sa.Column("primo_accesso", sa.Boolean, nullable=False),
        sa.Column("creato_il", sa.DateTime, nullable=False),
    )
    op.create_index("ix_utenti_email", "utenti", ["email"], unique=True)
    op.create_table(
        "unita",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nome", sa.String(50), nullable=False, unique=True),
        sa.Column("simbolo", sa.String(15), nullable=False),
    )
    op.create_table(
        "prodotti",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nome", sa.String(200), nullable=False),
        sa.Column("descrizione", sa.Text, nullable=False),
        sa.Column("categoria", sa.String(100), nullable=False),
        sa.Column("unita_id", sa.Integer, sa.ForeignKey("unita.id"), nullable=False),
        sa.Column("giacenza", sa.Float, nullable=False),
        sa.Column("scorta_minima", sa.Float, nullable=False),
        sa.Column("attivo", sa.Boolean, nullable=False),
        sa.Column("creato_il", sa.DateTime, nullable=False),
    )
    op.create_table(
        "ordini",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("docente_id", sa.Integer, sa.ForeignKey("utenti.id"), nullable=False),
        sa.Column("stato", sa.String(20), nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("nota_admin", sa.Text, nullable=False),
        sa.Column("creato_il", sa.DateTime, nullable=False),
        sa.Column("aggiornato_il", sa.DateTime, nullable=False),
        sa.Column("gestito_da_id", sa.Integer, sa.ForeignKey("utenti.id")),
    )
    op.create_table(
        "righe_ordine",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ordine_id", sa.Integer, sa.ForeignKey("ordini.id"), nullable=False),
        sa.Column("prodotto_id", sa.Integer, sa.ForeignKey("prodotti.id")),
        sa.Column("descrizione_libera", sa.String(255), nullable=False),
        sa.Column("richiesta_extra", sa.Boolean, nullable=False),
        sa.Column("unita_id", sa.Integer, sa.ForeignKey("unita.id"), nullable=False),
        sa.Column("quantita_richiesta", sa.Float, nullable=False),
        sa.Column("quantita_evasa", sa.Float, nullable=False),
    )
    op.create_table(
        "ordini_spesa",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fornitore", sa.String(200), nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("stato", sa.String(20), nullable=False),
        sa.Column("creato_da_id", sa.Integer, sa.ForeignKey("utenti.id"), nullable=False),
        sa.Column("ordine_origine_id", sa.Integer, sa.ForeignKey("ordini.id")),
        sa.Column("creato_il", sa.DateTime, nullable=False),
        sa.Column("inviato_il", sa.DateTime),
        sa.Column("ricevuto_il", sa.DateTime),
    )
    op.create_table(
        "righe_spesa",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ordine_spesa_id", sa.Integer, sa.ForeignKey("ordini_spesa.id"), nullable=False),
        sa.Column("prodotto_id", sa.Integer, sa.ForeignKey("prodotti.id"), nullable=False),
        sa.Column("quantita", sa.Float, nullable=False),
        sa.Column("prezzo_unitario", sa.Float),
    )


def downgrade():
    for t in ("righe_spesa", "ordini_spesa", "righe_ordine", "ordini", "prodotti", "unita", "utenti"):
        op.drop_table(t)
