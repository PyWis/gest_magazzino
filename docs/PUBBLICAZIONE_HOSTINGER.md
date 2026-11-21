# Pubblicare il gestionale su Hostinger (VPS)

Questa guida porta il gestionale online su un **VPS Hostinger**, con un indirizzo tipo
`https://magazzino.tuascuola.it`, HTTPS gratuito, avvio automatico e backup giornalieri.

> **Attenzione al piano.** I piani di *web hosting condiviso* di Hostinger (Single, Premium,
> Business, Cloud) **non** eseguono applicazioni Flask/Python: servono a siti PHP e WordPress.
> Per questo gestionale serve un piano **VPS** (basta il più piccolo, *KVM 1*).
> Se hai già un hosting condiviso, puoi tenerlo per il sito della scuola e usare il VPS solo per il magazzino.
> In alternativa c'è [PythonAnywhere](PUBBLICAZIONE_PYTHONANYWHERE.md), più semplice e con un piano gratuito.

Tempo stimato: 45–60 minuti la prima volta. Non serve essere esperti: basta copiare i comandi
uno alla volta. Dove vedi `magazzino.tuascuola.it` metti il tuo dominio.

---

## 0. Cosa ti serve

- Un VPS Hostinger (KVM 1 o superiore).
- Un dominio o sottodominio (es. `magazzino.tuascuola.it`). Può essere su Hostinger o altrove.
- Un programma per collegarti al server: su Windows 10/11 e macOS va bene il *Terminale*
  (comando `ssh`). In alternativa c'è il terminale nel browser di hPanel (*VPS → Terminale browser*).

## 1. Prepara il VPS in hPanel

1. In **hPanel → VPS** scegli il sistema operativo **Ubuntu 24.04** (modello "pulito", senza pannelli).
2. Imposta la **password di root** e annota l'**indirizzo IP** del VPS (es. `123.45.67.89`).
3. Se hPanel ha un **Firewall** per il VPS, consenti le porte **22 (SSH), 80 (HTTP) e 443 (HTTPS)**.

## 2. Punta il dominio al VPS

Nella gestione DNS del dominio (in hPanel: **Domini → DNS / Nameserver**) aggiungi un record:

| Tipo | Nome | Valore | TTL |
|---|---|---|---|
| A | `magazzino` | `123.45.67.89` (IP del VPS) | 3600 |

Per usare il dominio principale invece di un sottodominio, il nome è `@`.
La propagazione richiede da pochi minuti a qualche ora: intanto prosegui.

## 3. Collegati e installa i programmi necessari

Dal tuo computer:

```bash
ssh root@123.45.67.89
```

Poi, sul server:

```bash
apt update && apt upgrade -y
```

```bash
apt install -y python3 python3-venv python3-pip git nginx certbot python3-certbot-nginx ufw
```

Attiva il firewall del server (lascia aperti SSH e il sito):

```bash
ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw --force enable
```

## 4. Crea un utente dedicato e scarica il programma

Il gestionale gira con un utente senza privilegi, non come root:

```bash
adduser --system --group --home /opt/gest_magazzino magazzino
```

Se il repository GitHub è **privato**, prima crea un *token* di sola lettura:
GitHub → Settings → Developer settings → Personal access tokens → *Fine-grained tokens* →
accesso al solo repository `gest_magazzino` con permesso *Contents: Read-only*.
Poi fai ricordare il token al server, così anche gli aggiornamenti futuri non lo richiedono:

```bash
git config --global credential.helper store
```

Scarica il codice (se il repository è privato, quando chiede *Username* metti il tuo utente
GitHub e come *Password* incolla il token):

```bash
git clone https://github.com/PyWis/gest_magazzino.git /opt/gest_magazzino/app_src
```

Crea l'ambiente Python e installa le dipendenze:

```bash
cd /opt/gest_magazzino/app_src && python3 -m venv /opt/gest_magazzino/venv && /opt/gest_magazzino/venv/bin/pip install -r requirements.txt
```

Dai all'utente `magazzino` la proprietà dei file (il database verrà creato in `app_src/instance/`):

```bash
chown -R magazzino:magazzino /opt/gest_magazzino
```

## 5. Impostazioni

Crea il file delle impostazioni:

```bash
nano /etc/gest_magazzino.env
```

Incolla e adatta (salva con `Ctrl+O`, `Invio`, esci con `Ctrl+X`):

```ini
NOME_SCUOLA=IIS Galileo Galilei
TRUST_PROXY=1
COOKIE_SICURI=1

# Email ai docenti (facoltative). Esempio con Google Workspace / Gmail e "password per le app":
#MAIL_SERVER=smtp.gmail.com
#MAIL_PORT=587
#MAIL_USERNAME=magazzino@tuascuola.it
#MAIL_PASSWORD=la-password-per-le-app
#MAIL_FROM=Magazzino <magazzino@tuascuola.it>
```

- `TRUST_PROXY=1` serve perché davanti al programma c'è nginx: senza, il blocco dopo 5 password
  sbagliate bloccherebbe tutta la scuola insieme.
- `COOKIE_SICURI=1` va bene perché useremo HTTPS (passo 8). Se per qualche motivo resti in HTTP,
  mettilo a `0` altrimenti non riesci ad accedere.
- La chiave segreta viene generata da sola in `instance/secret_key`: non serve impostarla.

Proteggi il file (contiene la password email):

```bash
chmod 600 /etc/gest_magazzino.env
```

## 6. Avvio automatico del programma (systemd)

```bash
nano /etc/systemd/system/gest_magazzino.service
```

Incolla:

```ini
[Unit]
Description=Gestionale Magazzino
After=network.target

[Service]
User=magazzino
Group=magazzino
WorkingDirectory=/opt/gest_magazzino/app_src
EnvironmentFile=/etc/gest_magazzino.env
ExecStart=/opt/gest_magazzino/venv/bin/waitress-serve --host 127.0.0.1 --port 8000 --threads 8 run:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Avvia e controlla:

```bash
systemctl daemon-reload && systemctl enable --now gest_magazzino
```

```bash
systemctl status gest_magazzino --no-pager
```

Deve comparire **active (running)**. Al primo avvio viene creato il database.
Se c'è un errore, leggi il registro con `journalctl -u gest_magazzino -n 50 --no-pager`.

## 7. Nginx (il server web davanti al programma)

```bash
nano /etc/nginx/sites-available/gest_magazzino
```

Incolla (cambia il dominio):

```nginx
server {
    listen 80;
    server_name magazzino.tuascuola.it;

    client_max_body_size 5m;

    # file statici (grafica, icone, font) serviti direttamente da nginx
    location /static/ {
        alias /opt/gest_magazzino/app_src/app/static/;
        expires 7d;
        access_log off;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_read_timeout 60s;
    }
}
```

Attiva il sito e togli quello di esempio:

```bash
ln -s /etc/nginx/sites-available/gest_magazzino /etc/nginx/sites-enabled/ && rm -f /etc/nginx/sites-enabled/default
```

```bash
nginx -t && systemctl reload nginx
```

Ora `http://magazzino.tuascuola.it` deve mostrare la pagina di accesso (se il DNS è già propagato).

## 8. HTTPS gratuito (Let's Encrypt)

```bash
certbot --nginx -d magazzino.tuascuola.it --redirect -m tua-email@tuascuola.it --agree-tos -n
```

Il certificato si rinnova da solo. Ora il sito risponde su `https://magazzino.tuascuola.it`.

## 9. Primo accesso — fallo subito!

Apri il sito e accedi con **`admin@admin.test` / `admin`**. Il programma ti obbliga a scegliere
subito email e password personali: fallo immediatamente, perché ora il sito è raggiungibile da
internet. Poi crea gli altri admin e i docenti da *Utenti*.

## 10. Backup automatici

Una copia del database ogni notte alle 2:00, tenendo gli ultimi 30 giorni:

```bash
mkdir -p /var/backups/magazzino && chown magazzino:magazzino /var/backups/magazzino
```

```bash
echo '0 2 * * * magazzino /opt/gest_magazzino/venv/bin/python /opt/gest_magazzino/app_src/scripts/backup.py /var/backups/magazzino 30' > /etc/cron.d/gest_magazzino_backup
```

Prova subito che funziona:

```bash
sudo -u magazzino /opt/gest_magazzino/venv/bin/python /opt/gest_magazzino/app_src/scripts/backup.py /var/backups/magazzino 30
```

Ogni tanto **scarica una copia sul tuo computer** (un backup sullo stesso server non protegge se
il server si guasta). Dal tuo computer:

```bash
scp root@123.45.67.89:/var/backups/magazzino/*.db .
```

Hostinger offre anche backup/snapshot del VPS in hPanel: attivali come ulteriore sicurezza.

## 11. Aggiornare il programma

Quando su GitHub ci sono modifiche nuove (es. dopo aver unito una pull request in `main`):

```bash
cd /opt/gest_magazzino/app_src && sudo -u magazzino /opt/gest_magazzino/venv/bin/python scripts/backup.py /var/backups/magazzino 30
```

```bash
git config --global --add safe.directory /opt/gest_magazzino/app_src && git pull
```

```bash
/opt/gest_magazzino/venv/bin/pip install -r requirements.txt && chown -R magazzino:magazzino /opt/gest_magazzino && systemctl restart gest_magazzino
```

Il database viene aggiornato da solo al riavvio (migrazioni automatiche).

## 12. Ripristinare un backup

```bash
systemctl stop gest_magazzino
```

```bash
cp /var/backups/magazzino/magazzino-AAAA-MM-GG_HHMMSS.db /opt/gest_magazzino/app_src/instance/magazzino.db && chown magazzino:magazzino /opt/gest_magazzino/app_src/instance/magazzino.db
```

```bash
systemctl start gest_magazzino
```

## Problemi frequenti

| Sintomo | Causa probabile e soluzione |
|---|---|
| **502 Bad Gateway** | Il programma non è partito: `systemctl status gest_magazzino` e `journalctl -u gest_magazzino -n 50 --no-pager` |
| Il sito non si apre per nome ma con l'IP sì | Il DNS non è ancora propagato, o il record A è sbagliato |
| `certbot` fallisce | Il dominio non punta ancora al VPS, o le porte 80/443 sono chiuse nel firewall di hPanel |
| Dopo il login torna alla pagina di accesso | `COOKIE_SICURI=1` ma stai usando `http://`: usa `https://` oppure metti `COOKIE_SICURI=0` |
| Grafica senza stile | Controlla il percorso `alias` dei file statici nella configurazione nginx |
| Email non arrivano | Controlla le variabili `MAIL_*` e il registro (`journalctl -u gest_magazzino`); con Gmail serve una *password per le app* |
| "Troppi tentativi falliti" | Attendi 15 minuti oppure `systemctl restart gest_magazzino` (azzera i blocchi) |
| Password del superadmin persa | `cd /opt/gest_magazzino/app_src && sudo -u magazzino /opt/gest_magazzino/venv/bin/flask --app run reset-superadmin` poi accedi con `admin@admin.test` / `admin` |
