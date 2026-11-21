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

**Primo accesso:** `admin@admin.test` / `admin`. Il sistema obbliga il superadmin a scegliere
subito una nuova email e una nuova password: finché non lo fa non può usare nessun'altra pagina.

### Uso in rete (più PC della scuola)

```bash
waitress-serve --host 0.0.0.0 --port 5000 run:app
```

Imposta una chiave segreta fissa con la variabile d'ambiente `SECRET_KEY` (altrimenti ne viene
generata una e salvata in `instance/secret_key`). Per usare un altro database imposta `DATABASE_URL`.

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

## Flusso di lavoro

1. **Docente → Nuovo ordine.** Sceglie gli articoli dal catalogo del magazzino e la quantità
   (l'unità di misura è quella del prodotto). Se un articolo non c'è sceglie **«Altro…»**:
   compaiono i campi per descriverlo e scegliere l'unità di misura.
2. **Admin → Ordini docenti.** Per ogni riga vede quanto c'è in magazzino e indica quanto consegna ora
   (proposto in automatico). Alla consegna la giacenza viene scaricata.
   Si può consegnare in più volte: l'ordine passa a *Evaso in parte* e poi a *Evaso*.
   Le richieste «Altro» si trasformano in prodotto con **Crea prodotto da questa richiesta**
   oppure si collegano a un prodotto già esistente.
3. **Manca qualcosa?** Dall'ordine: **Crea ordine di spesa** genera una bozza con le quantità mancanti.
   Dal magazzino: **Riordina** genera una bozza con i prodotti sotto scorta minima.
4. **Ordine di spesa:** bozza → *inviato al fornitore* → **Merce ricevuta** (carica le quantità in magazzino).
   Poi si torna sull'ordine del docente e lo si evade.

## Unità di misura

Predefinite: pezzi, confezioni, litri, millilitri, kg, grammi, metri, centimetri, m².
Gli admin possono aggiungerne altre da *Magazzino → Unità di misura*.
Le quantità accettano decimali con virgola o punto (es. `1,5`).

## Struttura

```
run.py                 avvio
app/__init__.py        configurazione, dati iniziali, comando reset-superadmin
app/models.py          tabelle (utenti, unità, prodotti, ordini, ordini di spesa)
app/utils.py           permessi, CSRF, primo accesso obbligatorio, formattazione
app/routes/            auth, utenti, prodotti (magazzino), ordini, spesa
app/templates/         pagine HTML (Bootstrap 5)
```
