"""Copia di sicurezza del database SQLite del magazzino.

Uso:  python scripts/backup.py [cartella_destinazione] [copie_da_tenere]

Esempio (dalla cartella del progetto):
    python scripts/backup.py                    # -> backup/magazzino-AAAA-MM-GG_HHMMSS.db, tiene 30 copie
    python scripts/backup.py /var/backups/magazzino 60

Usa l'API di backup di SQLite: la copia è coerente anche se il gestionale è in uso.
"""
import os
import sqlite3
import sys
from datetime import datetime

PROGETTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE = os.path.join(PROGETTO, "instance", "magazzino.db")


def main():
    destinazione = sys.argv[1] if len(sys.argv) > 1 else os.path.join(PROGETTO, "backup")
    da_tenere = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    if not os.path.exists(DATABASE):
        sys.exit(f"Database non trovato: {DATABASE}")
    os.makedirs(destinazione, exist_ok=True)

    nome = f"magazzino-{datetime.now():%Y-%m-%d_%H%M%S}.db"
    percorso = os.path.join(destinazione, nome)
    with sqlite3.connect(DATABASE) as sorgente, sqlite3.connect(percorso) as copia:
        sorgente.backup(copia)
    print(f"Backup creato: {percorso}")

    # elimina le copie più vecchie oltre il numero da tenere
    copie = sorted(f for f in os.listdir(destinazione) if f.startswith("magazzino-") and f.endswith(".db"))
    for vecchia in copie[:-da_tenere]:
        os.remove(os.path.join(destinazione, vecchia))
        print(f"Eliminato backup vecchio: {vecchia}")


if __name__ == "__main__":
    main()
