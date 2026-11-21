# Gestionale Magazzino (Flask)

Gestionale per il magazzino della scuola: i docenti ordinano il materiale, gli admin evadono gli ordini,
gestiscono le giacenze e creano gli ordini di spesa per ciò che manca.

## Installazione

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python run.py                     # poi apri http://127.0.0.1:5000
```

Al primo avvio viene creato il database SQLite in `instance/magazzino.db`.
Ad ogni avvio il database viene **aggiornato automaticamente** all'ultima versione (migrazioni in
`app/migrations/`): un database creato con le versioni precedenti viene riconosciuto e convertito
senza perdere dati. Fai comunque una copia di `instance/magazzino.db` prima di aggiornare il programma.

Grafica, icone e font sono inclusi in `app/static/vendor/`: il gestionale funziona anche senza
connessione a internet.

**Primo accesso:** `admin@admin.test` / `admin`. Il sistema obbliga il superadmin a scegliere
subito una nuova email e una nuova password: finché non lo fa non può usare nessun'altra pagina.

### Uso in rete (più PC della scuola)

```bash
waitress-serve --host 0.0.0.0 --port 5000 run:app
```

Imposta una chiave segreta fissa con la variabile d'ambiente `SECRET_KEY` (altrimenti ne viene
generata una e salvata in `instance/secret_key`). Per usare un altro database imposta `DATABASE_URL`.

### Impostazioni (variabili d'ambiente)

| Variabile | A cosa serve |
|---|---|
| `NOME_SCUOLA` | Nome mostrato nel menu, nel login e nei documenti d'ordine (es. `IIS Galileo Galilei`) |
| `SECRET_KEY` | Chiave segreta fissa (altrimenti generata in `instance/secret_key`) |
| `DATABASE_URL` | Database diverso da SQLite |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM` | Server email per avvisare i docenti quando un ordine cambia stato. Se `MAIL_SERVER` è vuoto le email sono disattivate |
| `MAIL_USE_TLS` / `MAIL_USE_SSL` | Tipo di connessione al server email (predefinito: STARTTLS) |

Esempio con Gmail / Google Workspace (serve una «password per le app»):
`MAIL_SERVER=smtp.gmail.com MAIL_PORT=587 MAIL_USERNAME=magazzino@scuola.it MAIL_PASSWORD=...`

### Credenziali dimenticate

```bash
flask --app run reset-superadmin
```
Riporta il superadmin a `admin@admin.test` / `admin` con cambio obbligatorio al prossimo accesso.

## Ruoli

| Ruolo | Cosa può fare |
|---|---|
| **Superadmin** | Tutto ciò che fa un admin + crea/modifica/disattiva gli **admin** |
| **Admin** | Crea/modifica/disattiva i **docenti**, gestisce magazzino, unità di misura, ordini e ordini di spesa |
| **Docente** | Crea ordini, vede lo stato dei propri ordini, può annullarli finché non sono presi in carico |

Ogni utente creato da un admin riceve una password temporanea e deve cambiarla al primo accesso.
Gli utenti non si cancellano (hanno uno storico ordini): si disattivano.
Dopo 5 tentativi di accesso sbagliati l'account e l'indirizzo vengono bloccati per 15 minuti.

## Flusso di lavoro

1. **Docente → Nuovo ordine.** Cerca gli articoli nel catalogo (vede subito la disponibilità) e indica
   la quantità. Se un articolo non c'è sceglie **«Altro…»** e lo descrive.
   Da un vecchio ordine può usare **Ripeti ordine**. Se il server email è configurato riceve un avviso
   quando l'ordine viene evaso, chiuso o rifiutato (disattivabile dal profilo).
2. **Admin → Ordini docenti.** Per ogni riga vede quanto c'è in magazzino e indica quanto consegna ora
   (proposto in automatico). Alla consegna la giacenza viene scaricata.
   Si può consegnare in più volte: l'ordine passa a *Evaso in parte* e poi a *Evaso*.
   Le richieste «Altro» si trasformano in prodotto con **Crea prodotto da questa richiesta**
   oppure si collegano a un prodotto già esistente. Se le unità sono diverse la quantità viene
   **convertita** (es. 500 ml → 0,5 l); se non sono convertibili (pezzi → confezioni) l'admin la indica.
3. **Manca qualcosa?** Dall'ordine: **Crea ordine di spesa** genera una bozza con le quantità mancanti.
   Dal magazzino: **Riordina** genera una bozza con i prodotti sotto scorta minima.
   In entrambi i casi si tiene conto di **tutti gli ordini aperti** e di quanto è **già in arrivo**
   da altri ordini di spesa (bozze comprese), così non si compra due volte la stessa cosa.
4. **Ordine di spesa:** bozza → *inviato al fornitore* → **Registra merce ricevuta**: si indica quanto è
   arrivato davvero, anche in più volte (*ricevuto in parte*). Il fornitore si sceglie dall'anagrafica
   *Fornitori*. L'ordine si può stampare / salvare in PDF, esportare per Excel o inviare per email.
   Poi si torna sull'ordine del docente e lo si evade.

## Giacenze e registro movimenti

La giacenza di un prodotto cambia **solo** tramite movimenti, tutti registrati in *Magazzino → Movimenti*
(con data, utente, quantità, giacenza risultante e riferimento all'ordine):

- **Scarico**: consegna a un docente
- **Carico**: merce ricevuta da un ordine di spesa
- **Rettifica**: correzione dopo un conteggio (inventario, merce rotta…), con motivo obbligatorio
- **Giacenza iniziale**: alla creazione del prodotto

Nel modulo di modifica del prodotto la giacenza non è modificabile: si usa **Rettifica giacenza** dalla
scheda prodotto. Se nel frattempo un collega ha registrato una consegna, la rettifica viene rifiutata
invece di sovrascriverla. Inventario e movimenti si esportano in CSV (si apre in Excel).

## Unità di misura

Predefinite: pezzi, confezioni, litri, millilitri, kg, grammi, metri, centimetri, m².
Gli admin possono aggiungerne altre da *Magazzino → Unità di misura*, indicando il tipo di grandezza
(volume, massa, lunghezza, superficie) e il fattore di conversione per renderle convertibili.
Le quantità accettano decimali con virgola o punto (es. `1,5`).

## Struttura

```
run.py                 avvio
app/__init__.py        configurazione, aggiornamento database, dati iniziali, reset-superadmin
app/models.py          tabelle (utenti, unità, prodotti, movimenti, ordini, fornitori, ordini di spesa)
app/magazzino.py       movimenti di giacenza, fabbisogni, merce in arrivo, conversione unità
app/utils.py           permessi, CSRF, blocco login, email, formattazione, CSV
app/routes/            auth, utenti, prodotti (magazzino), ordini, spesa
app/migrations/        migrazioni del database (Alembic / Flask-Migrate)
app/templates/         pagine HTML (Bootstrap 5, tema blu/azzurro, tema scuro automatico)
app/static/            stile e librerie incluse (Bootstrap, icone, Tom Select, font Inter)
tests/                 test automatici
```

## Test

```bash
pip install -r requirements-dev.txt
pytest
```
