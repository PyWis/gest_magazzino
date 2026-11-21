"""Registro movimenti, fornitori, ricezioni parziali, conversione unità, quantità decimali esatte

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21
"""
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

Q = sa.Numeric(14, 3)

# simbolo -> (gruppo, fattore) per le unità predefinite già presenti
CONVERSIONI = {
    "l": ("volume", "1"), "ml": ("volume", "0.001"),
    "kg": ("massa", "1"), "g": ("massa", "0.001"),
    "m": ("lunghezza", "1"), "cm": ("lunghezza", "0.01"),
    "m²": ("superficie", "1"),
}


def upgrade():
    conn = op.get_bind()

    # --- utenti: preferenza notifiche email
    with op.batch_alter_table("utenti") as b:
        b.add_column(sa.Column("notifiche_email", sa.Boolean, nullable=False, server_default=sa.true()))

    # --- unità: gruppo e fattore di conversione
    with op.batch_alter_table("unita") as b:
        b.add_column(sa.Column("gruppo", sa.String(20), nullable=False, server_default=""))
        b.add_column(sa.Column("fattore", sa.Numeric(18, 6)))
    unita = sa.table("unita", sa.column("simbolo"), sa.column("gruppo"), sa.column("fattore"))
    for simbolo, (gruppo, fattore) in CONVERSIONI.items():
        conn.execute(unita.update().where(unita.c.simbolo == simbolo)
                     .values(gruppo=gruppo, fattore=fattore))

    # --- quantità: da Float a Numeric (decimali esatti)
    with op.batch_alter_table("prodotti") as b:
        b.alter_column("giacenza", type_=Q, existing_nullable=False)
        b.alter_column("scorta_minima", type_=Q, existing_nullable=False)
    with op.batch_alter_table("righe_ordine") as b:
        b.alter_column("quantita_richiesta", type_=Q, existing_nullable=False)
        b.alter_column("quantita_evasa", type_=Q, existing_nullable=False)
        b.add_column(sa.Column("richiesta_originale", sa.String(60), nullable=False, server_default=""))

    # --- fornitori
    op.create_table(
        "fornitori",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nome", sa.String(200), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False, server_default=""),
        sa.Column("telefono", sa.String(50), nullable=False, server_default=""),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("attivo", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    with op.batch_alter_table("ordini_spesa") as b:
        b.add_column(sa.Column("fornitore_id", sa.Integer))
        b.create_foreign_key("fk_ordini_spesa_fornitore", "fornitori", ["fornitore_id"], ["id"])

    # i fornitori scritti a mano negli ordini di spesa diventano schede fornitore
    fornitori = sa.table("fornitori", sa.column("id"), sa.column("nome"))
    spese = sa.table("ordini_spesa", sa.column("fornitore"), sa.column("fornitore_id"))
    nomi = {}
    for (testo,) in conn.execute(sa.select(spese.c.fornitore).distinct()):
        nome = (testo or "").strip()
        if nome and nome.lower() not in nomi:
            conn.execute(fornitori.insert().values(nome=nome))
            nomi[nome.lower()] = conn.execute(
                sa.select(fornitori.c.id).where(fornitori.c.nome == nome)).scalar()
    for (testo,) in conn.execute(sa.select(spese.c.fornitore).distinct()):
        fid = nomi.get((testo or "").strip().lower())
        if fid:
            conn.execute(spese.update().where(spese.c.fornitore == testo).values(fornitore_id=fid))

    # --- righe di spesa: quantità ricevuta (ricezioni parziali)
    with op.batch_alter_table("righe_spesa") as b:
        b.alter_column("quantita", type_=Q, existing_nullable=False)
        b.alter_column("prezzo_unitario", type_=sa.Numeric(12, 2))
        b.add_column(sa.Column("quantita_ricevuta", Q, nullable=False, server_default="0"))
    conn.execute(sa.text(
        "UPDATE righe_spesa SET quantita_ricevuta = quantita WHERE ordine_spesa_id IN "
        "(SELECT id FROM ordini_spesa WHERE stato = 'ricevuto')"))

    # --- registro movimenti
    op.create_table(
        "movimenti",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("prodotto_id", sa.Integer, sa.ForeignKey("prodotti.id"), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("quantita", Q, nullable=False),
        sa.Column("giacenza_dopo", Q, nullable=False),
        sa.Column("nota", sa.String(255), nullable=False, server_default=""),
        sa.Column("utente_id", sa.Integer, sa.ForeignKey("utenti.id")),
        sa.Column("ordine_id", sa.Integer, sa.ForeignKey("ordini.id")),
        sa.Column("ordine_spesa_id", sa.Integer, sa.ForeignKey("ordini_spesa.id")),
        sa.Column("creato_il", sa.DateTime, nullable=False),
    )
    op.create_index("ix_movimenti_prodotto_id", "movimenti", ["prodotto_id"])
    op.create_index("ix_movimenti_creato_il", "movimenti", ["creato_il"])

    # punto di partenza dello storico: la giacenza attuale di ogni prodotto
    movimenti = sa.table("movimenti", sa.column("prodotto_id"), sa.column("tipo"),
                         sa.column("quantita"), sa.column("giacenza_dopo"),
                         sa.column("nota"), sa.column("creato_il", sa.DateTime))
    ora = datetime.now()
    for pid, giacenza in conn.execute(sa.text("SELECT id, giacenza FROM prodotti")):
        conn.execute(movimenti.insert().values(
            prodotto_id=pid, tipo="iniziale", quantita=giacenza, giacenza_dopo=giacenza,
            nota="Giacenza al momento dell'attivazione del registro movimenti", creato_il=ora))


def downgrade():
    op.drop_table("movimenti")
    with op.batch_alter_table("righe_spesa") as b:
        b.drop_column("quantita_ricevuta")
    with op.batch_alter_table("ordini_spesa") as b:
        b.drop_constraint("fk_ordini_spesa_fornitore", type_="foreignkey")
        b.drop_column("fornitore_id")
    op.drop_table("fornitori")
    with op.batch_alter_table("righe_ordine") as b:
        b.drop_column("richiesta_originale")
    with op.batch_alter_table("unita") as b:
        b.drop_column("fattore")
        b.drop_column("gruppo")
    with op.batch_alter_table("utenti") as b:
        b.drop_column("notifiche_email")
