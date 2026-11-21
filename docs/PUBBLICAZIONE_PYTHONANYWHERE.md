# Pubblicare il gestionale su PythonAnywhere

[PythonAnywhere](https://www.pythonanywhere.com) è un servizio fatto apposta per le applicazioni
Python: non c'è un server da gestire e c'è un **piano gratuito**. È il modo più semplice per mettere
online il gestionale.

Tempo stimato: 20–30 minuti. Nella guida `NOMEUTENTE` è il tuo nome utente PythonAnywhere:
sostituiscilo ovunque.

---

## Gratuito o a pagamento?

| | Gratuito (*Beginner*) | A pagamento (da *Hacker* in su) |
|---|---|---|
| Indirizzo | `https://NOMEUTENTE.pythonanywhere.com` | anche un dominio tuo, es. `magazzino.tuascuola.it` |
| Scadenza | il sito si **ferma se non lo rinnovi** con un clic dalla scheda *Web* (oggi ogni mese, controlla la data indicata lì) | nessuna |
| Email ai docenti | solo tramite **Gmail / Google Workspace** (`smtp.gmail.com`) | qualsiasi server email |
| Backup programmati | 1 attività programmata al giorno | di più |

Per una scuola il piano gratuito va bene per provare. Per l'uso quotidiano conviene il piano
*Hacker*, che non scade e permette il dominio della scuola.

> Se ti registri dall'Europa puoi scegliere il server europeo (`eu.pythonanywhere.com`):
> i dati restano nell'UE, utile per la privacy (GDPR). In quel caso l'indirizzo sarà
> `NOMEUTENTE.eu.pythonanywhere.com`.

---

## 1. Crea l'account

Registrati su [pythonanywhere.com](https://www.pythonanywhere.com) (o su `eu.pythonanywhere.com`)
e conferma l'email. Il nome utente sarà nell'indirizzo del sito: scegline uno chiaro,
es. `magazzinogalilei`.

## 2. Scarica il programma

Apri la scheda **Consoles → Bash** (si apre un terminale nel browser) ed esegui:

```bash
git clone https://github.com/PyWis/gest_magazzino.git
```

Se il repository GitHub è **privato**, crea prima un *token* di sola lettura
(GitHub → Settings → Developer settings → Personal access tokens → *Fine-grained tokens* →
solo il repository `gest_magazzino`, permesso *Contents: Read-only*). Quando `git clone` chiede
*Username* metti il tuo utente GitHub, come *Password* incolla il token. Per non doverlo
reinserire a ogni aggiornamento, prima del clone esegui:

```bash
git config --global credential.helper store
```

## 3. Crea l'ambiente Python e installa le dipendenze

Sempre nella console Bash:

```bash
mkvirtualenv --python=/usr/bin/python3.12 magazzino
```

```bash
cd ~/gest_magazzino && pip install -r requirements.txt
```

(Se `python3.12` non esiste, usa la versione più recente elencata da `ls /usr/bin/python3.*`;
serve almeno la 3.10.)

## 4. Crea l'applicazione web

1. Vai nella scheda **Web** → **Add a new web app** → *Next*.
2. Scegli **Manual configuration** (non "Flask"!) → la **stessa versione di Python** del passo 3 → *Next*.
3. Nella pagina dell'app, sezione **Virtualenv**, inserisci:
   ```
   /home/NOMEUTENTE/.virtualenvs/magazzino
   ```
4. Sezione **Code**:
   - *Source code*: `/home/NOMEUTENTE/gest_magazzino`
   - *Working directory*: `/home/NOMEUTENTE/gest_magazzino`
5. Sezione **Static files**, aggiungi una riga:

   | URL | Directory |
   |---|---|
   | `/static/` | `/home/NOMEUTENTE/gest_magazzino/app/static` |

6. Sezione **Security**: attiva **Force HTTPS**.

## 5. Configura il file WSGI

Sempre nella scheda **Web**, sezione *Code*, clicca sul link del **WSGI configuration file**
(`/var/www/NOMEUTENTE_pythonanywhere_com_wsgi.py`). **Cancella tutto** il contenuto e incolla:

```python
import os
import sys

PROGETTO = "/home/NOMEUTENTE/gest_magazzino"
if PROGETTO not in sys.path:
    sys.path.insert(0, PROGETTO)

# ---- impostazioni del gestionale
os.environ["NOME_SCUOLA"] = "IIS Galileo Galilei"
os.environ["TRUST_PROXY"] = "1"      # necessario su PythonAnywhere (IP reale dei visitatori)
os.environ["COOKIE_SICURI"] = "1"    # il sito è in HTTPS

# ---- email ai docenti (facoltative). Sul piano gratuito funziona solo Gmail / Google Workspace,
# con una "password per le app" (Account Google → Sicurezza → Verifica in due passaggi → Password per le app)
# os.environ["MAIL_SERVER"] = "smtp.gmail.com"
# os.environ["MAIL_PORT"] = "587"
# os.environ["MAIL_USERNAME"] = "magazzino@tuascuola.it"
# os.environ["MAIL_PASSWORD"] = "la-password-per-le-app"
# os.environ["MAIL_FROM"] = "Magazzino <magazzino@tuascuola.it>"

from run import app as application  # noqa: E402
```

Sostituisci `NOMEUTENTE` e il nome della scuola, poi **Save**.

> La chiave segreta viene generata da sola in `gest_magazzino/instance/secret_key` e il database
> in `gest_magazzino/instance/magazzino.db`: non c'è altro da configurare.

## 6. Avvia

Torna nella scheda **Web** e premi il grande pulsante verde **Reload**.
Apri `https://NOMEUTENTE.pythonanywhere.com`: deve comparire la pagina di accesso.

Se vedi *"Something went wrong"*, apri l'**Error log** (link nella scheda *Web*, sezione *Log files*):
l'ultima riga in fondo dice cosa non va (di solito un percorso sbagliato nel file WSGI o il
virtualenv non indicato).

## 7. Primo accesso — fallo subito!

Accedi con **`admin@admin.test` / `admin`**. Il programma ti obbliga a scegliere subito email e
password personali: fallo immediatamente, perché il sito è già raggiungibile da internet.
Poi crea gli altri admin e i docenti da *Utenti*.

## 8. Piano gratuito: rinnova il sito

Nella scheda **Web** è indicata la data di scadenza: prima di quella data premi
**"Run until … from today"**, altrimenti il sito si ferma (i dati **non** vengono persi:
basta rinnovarlo e premere *Reload*). PythonAnywhere manda un'email di promemoria qualche giorno prima.
Metti un promemoria anche nel calendario.

## 9. Backup automatici

Nella scheda **Tasks** crea un'attività giornaliera (es. alle 02:00 UTC) con questo comando:

```bash
/home/NOMEUTENTE/.virtualenvs/magazzino/bin/python /home/NOMEUTENTE/gest_magazzino/scripts/backup.py /home/NOMEUTENTE/backup_magazzino 30
```

Tiene gli ultimi 30 backup nella cartella `backup_magazzino`. Prova il comando una volta dalla
console Bash per verificare che funzioni.

Ogni tanto **scarica una copia sul tuo computer**: scheda **Files** → cartella
`backup_magazzino` → clic sul file → *Download*. Un backup che resta solo su PythonAnywhere non
protegge se perdi l'accesso all'account.

## 10. Usare il dominio della scuola (solo piani a pagamento)

1. Scheda **Web** → **Add a new web app** → inserisci `magazzino.tuascuola.it` e ripeti i passi 4–5
   (virtualenv, cartelle, file statici, file WSGI: il nuovo file WSGI avrà un nome diverso).
   Il database è lo stesso, perché sta nella cartella del progetto.
2. Nel DNS del dominio crea un record **CNAME**: nome `magazzino`, valore
   `webapp-XXXXXX.pythonanywhere.com` (il valore esatto è indicato nella scheda *Web*).
3. Nella sezione *Security* attiva il certificato HTTPS gratuito (*Let's Encrypt*) e *Force HTTPS*.

## 11. Aggiornare il programma

Quando su GitHub ci sono modifiche nuove (es. dopo aver unito una pull request in `main`),
dalla console Bash:

```bash
workon magazzino && cd ~/gest_magazzino && python scripts/backup.py ~/backup_magazzino 30
```

```bash
git pull && pip install -r requirements.txt
```

Poi scheda **Web** → **Reload**. Il database viene aggiornato da solo al riavvio (migrazioni automatiche).

## 12. Ripristinare un backup

Dalla console Bash (scegli il file giusto con `ls ~/backup_magazzino`):

```bash
cp ~/backup_magazzino/magazzino-AAAA-MM-GG_HHMMSS.db ~/gest_magazzino/instance/magazzino.db
```

Poi scheda **Web** → **Reload**.

## Problemi frequenti

| Sintomo | Causa probabile e soluzione |
|---|---|
| *Something went wrong :-(* | Leggi l'**Error log** nella scheda *Web*: di solito `NOMEUTENTE` non sostituito nel file WSGI, o virtualenv non impostato |
| `ModuleNotFoundError: No module named 'flask'` | Virtualenv mancante o sbagliato nella scheda *Web*, oppure versione di Python dell'app diversa da quella del virtualenv |
| Grafica senza stile | Controlla la riga *Static files* (`/static/` → `.../gest_magazzino/app/static`) e premi *Reload* |
| Dopo il login torna alla pagina di accesso | Stai usando `http://`: attiva *Force HTTPS* (oppure metti `COOKIE_SICURI` a `"0"`) |
| Email non partono (piano gratuito) | Funziona solo `smtp.gmail.com` con una *password per le app*; altri server sono bloccati |
| Il sito non risponde più | Sul piano gratuito è scaduto: scheda *Web* → *Run until…* → *Reload* |
| "Troppi tentativi falliti" | Attendi 15 minuti oppure premi *Reload* (azzera i blocchi) |
| Password del superadmin persa | Console Bash: `workon magazzino && cd ~/gest_magazzino && flask --app run reset-superadmin`, poi accedi con `admin@admin.test` / `admin` |
