from decimal import Decimal

from flask_migrate import downgrade, upgrade
from sqlalchemy import text

from app import CARTELLA_MIGRAZIONI
from app.models import (Fornitore, Movimento, Ordine, OrdineSpesa, Prodotto, RigaOrdine, StatoOrdine,
                        StatoSpesa, Utente, db)
from app.utils import parse_qta

from .conftest import Client, crea_prodotto


def get(app, modello, id_):
    with app.app_context():
        return db.session.get(modello, id_)


def ordina(docente, righe, note=""):
    """righe: lista di (prodotto_id|'altro', quantita, descrizione, unita_id)"""
    data = {"prodotto_id": [], "quantita": [], "descrizione": [], "unita_id": [], "note": note}
    for pid, q, d, u in righe:
        data["prodotto_id"].append(str(pid))
        data["quantita"].append(q)
        data["descrizione"].append(d)
        data["unita_id"].append(str(u))
    r = docente.post("/ordini/nuovo", data)
    assert r.status_code == 302, r.get_data(as_text=True)
    return int(r.headers["Location"].rstrip("/").split("/")[-1])


def righe_di(app, oid):
    with app.app_context():
        return [(r.id, r.prodotto_id) for r in db.session.get(Ordine, oid).righe]


# ------------------------------------------------------------------ base

def test_parse_qta():
    assert parse_qta("1,5") == Decimal("1.500")
    assert parse_qta("1.234,5") == Decimal("1234.500")
    assert parse_qta("abc") is None and parse_qta("") is None and parse_qta("nan") is None
    assert parse_qta("0,1") + parse_qta("0,2") == Decimal("0.3")  # niente errori da virgola mobile


def test_pagine_si_aprono(app, admin, docente):
    pid = crea_prodotto(app, "Carta A4", "conf", "10", "5")
    oid = ordina(docente, [(pid, "2", "", "")])
    for url in ["/", "/ordini/", "/ordini/?stato=tutti&q=Dario", f"/ordini/{oid}", "/magazzino/",
                "/magazzino/?filtro=sotto_scorta", f"/magazzino/{pid}", f"/magazzino/{pid}/modifica",
                "/magazzino/nuovo", "/magazzino/movimenti", "/magazzino/unita", "/spesa/",
                "/spesa/nuovo", "/spesa/fornitori", "/spesa/fornitori/nuovo", "/utenti/",
                "/utenti/nuovo", "/profilo"]:
        assert admin.get(url).status_code == 200, url
    for url in ["/ordini/miei", "/ordini/nuovo", f"/ordini/{oid}", f"/ordini/nuovo?da={oid}", "/profilo"]:
        assert docente.get(url).status_code == 200, url
    for url in ["/magazzino/", "/spesa/", "/utenti/", "/ordini/"]:
        assert docente.get(url).status_code == 403, url


def test_pagina_non_trovata(admin):
    r = admin.get("/ordini/9999")
    assert r.status_code == 404 and "Pagina non trovata" in r.get_data(as_text=True)


# ------------------------------------------------------------------ bug A: conversione unità

def test_collega_altro_converte_unita(app, admin, docente, unita):
    pid = crea_prodotto(app, "Alcol etilico", "l", "2")
    oid = ordina(docente, [("altro", "500", "Alcol 90°", unita["ml"])])
    (rid, _), = righe_di(app, oid)
    admin.post(f"/ordini/{oid}/gestisci", {"azione": "consegna", f"collega_{rid}": pid})
    riga = get(app, RigaOrdine, rid)
    assert riga.prodotto_id == pid
    assert riga.unita_id == unita["l"]
    assert riga.quantita_richiesta == Decimal("0.5")          # 500 ml -> 0,5 l (prima diventava 500 l!)
    assert riga.richiesta_originale == "500 ml"


def test_collega_unita_non_convertibile_chiede_quantita(app, admin, docente, unita):
    pid = crea_prodotto(app, "Pipette (conf. da 100)", "conf", "3")
    oid = ordina(docente, [("altro", "50", "Pipette Pasteur", unita["pz"])])
    (rid, _), = righe_di(app, oid)
    r = admin.post(f"/ordini/{oid}/gestisci", {"azione": "consegna", f"collega_{rid}": pid},
                   follow_redirects=True)
    assert "Indica la quantità in conf" in r.get_data(as_text=True)
    assert get(app, RigaOrdine, rid).prodotto_id is None
    admin.post(f"/ordini/{oid}/gestisci", {"azione": "consegna", f"collega_{rid}": pid,
                                           f"qta_collega_{rid}": "1"})
    riga = get(app, RigaOrdine, rid)
    assert riga.prodotto_id == pid and riga.quantita_richiesta == 1


def test_crea_prodotto_da_richiesta_converte(app, admin, docente, unita):
    oid = ordina(docente, [("altro", "250", "Colla vinilica", unita["g"])])
    (rid, _), = righe_di(app, oid)
    r = admin.post(f"/magazzino/nuovo?da_riga={rid}", {"nome": "Colla vinilica", "unita_id": unita["kg"],
                                                       "giacenza": "0", "scorta_minima": "0"})
    assert r.status_code == 302
    riga = get(app, RigaOrdine, rid)
    assert riga.prodotto_id and riga.quantita_richiesta == Decimal("0.25")


# ------------------------------------------------------------------ bug B: giacenza e movimenti

def test_modifica_prodotto_non_tocca_giacenza(app, admin, unita):
    pid = crea_prodotto(app, "Penne", "pz", "10")
    admin.get(f"/magazzino/{pid}/modifica")
    # intanto un altro admin consegna 4 penne...
    from app.magazzino import muovi
    from app.models import TipoMovimento
    with app.app_context():
        muovi(db.session.get(Prodotto, pid), -4, TipoMovimento.SCARICO)
        db.session.commit()
    # ...e il primo salva il form aperto prima: la giacenza non deve tornare a 10
    admin.post(f"/magazzino/{pid}/modifica", {"nome": "Penne blu", "unita_id": unita["pz"], "giacenza": "10",
                                              "scorta_minima": "2", "attivo": "1"})
    p = get(app, Prodotto, pid)
    assert p.nome == "Penne blu" and p.giacenza == 6


def test_rettifica_con_controllo_concorrenza(app, admin):
    pid = crea_prodotto(app, "Gesso", "conf", "10")
    r = admin.post(f"/magazzino/{pid}/rettifica", {"giacenza": "8", "giacenza_vista": "10", "motivo": "Inventario"},
                   follow_redirects=True)
    assert "rettificata a 8" in r.get_data(as_text=True)
    # valore visto non più attuale -> rifiutata
    r = admin.post(f"/magazzino/{pid}/rettifica", {"giacenza": "5", "giacenza_vista": "10", "motivo": "x"},
                   follow_redirects=True)
    assert "Nel frattempo la giacenza" in r.get_data(as_text=True)
    assert get(app, Prodotto, pid).giacenza == 8
    with app.app_context():
        m = Movimento.query.filter_by(prodotto_id=pid, tipo="rettifica").one()
        assert m.quantita == -2 and m.nota == "Inventario" and m.utente.email == "admin@scuola.it"


def test_consegna_scarica_e_registra(app, admin, docente):
    pid = crea_prodotto(app, "Carta A4", "conf", "5")
    oid = ordina(docente, [(pid, "3", "", "")])
    (rid, _), = righe_di(app, oid)
    admin.post(f"/ordini/{oid}/gestisci", {"azione": "consegna", f"consegna_{rid}": "2"})
    assert get(app, Ordine, oid).stato == StatoOrdine.PARZIALE
    assert get(app, Prodotto, pid).giacenza == 3
    admin.post(f"/ordini/{oid}/gestisci", {"azione": "consegna", f"consegna_{rid}": "1"})
    assert get(app, Ordine, oid).stato == StatoOrdine.EVASO
    with app.app_context():
        scarichi = Movimento.query.filter_by(prodotto_id=pid, tipo="scarico").all()
        assert [m.quantita for m in scarichi] == [-2, -1]
        assert scarichi[-1].giacenza_dopo == 2 and scarichi[-1].ordine_id == oid
        # il docente riceve le email di cambio stato
        inviate = app.extensions["email_inviate"]
        assert [m["To"] for m in inviate] == ["doc@scuola.it", "doc@scuola.it"]
        assert "evaso" in inviate[-1]["Subject"]


def test_consegna_oltre_giacenza_rifiutata(app, admin, docente):
    pid = crea_prodotto(app, "Toner", "pz", "1")
    oid = ordina(docente, [(pid, "3", "", "")])
    (rid, _), = righe_di(app, oid)
    r = admin.post(f"/ordini/{oid}/gestisci", {"azione": "consegna", f"consegna_{rid}": "2"},
                   follow_redirects=True)
    assert "ce ne sono solo 1" in r.get_data(as_text=True)
    assert get(app, Prodotto, pid).giacenza == 1


# ------------------------------------------------------------------ bug C: niente acquisti doppi

def test_riordino_sotto_scorta_non_duplica(app, admin):
    crea_prodotto(app, "Guanti", "conf", "1", "5")
    admin.post("/spesa/da-sotto-scorta")
    with app.app_context():
        spesa = OrdineSpesa.query.one()
        assert spesa.righe[0].quantita == 9   # 2×5 - 1
    r = admin.post("/spesa/da-sotto-scorta", follow_redirects=True)
    assert "Già coperti" in r.get_data(as_text=True)
    with app.app_context():
        assert OrdineSpesa.query.count() == 1


def test_spesa_da_ordine_considera_tutta_la_domanda(app, admin, docente):
    pid = crea_prodotto(app, "Carta A4", "conf", "2")
    o1 = ordina(docente, [(pid, "3", "", "")])
    ordina(docente, [(pid, "4", "", "")])
    admin.post(f"/ordini/{o1}/ordine-spesa")
    with app.app_context():
        assert OrdineSpesa.query.one().righe[0].quantita == 5   # 3 + 4 richiesti - 2 in magazzino
    r = admin.post(f"/ordini/{o1}/ordine-spesa", follow_redirects=True)
    assert "Non serve comprare nulla" in r.get_data(as_text=True)


# ------------------------------------------------------------------ bug D: ricezione parziale

def test_ricezione_parziale(app, admin):
    pid = crea_prodotto(app, "Risme", "conf", "0")
    admin.post("/spesa/nuovo", {"prodotto_id": [str(pid)], "quantita": ["10"], "prezzo": ["3,50"],
                                "fornitore_id": "nuovo", "fornitore_nuovo": "Cartoleria Rossi"})
    with app.app_context():
        s = OrdineSpesa.query.one()
        sid, rid = s.id, s.righe[0].id
        assert s.fornitore.nome == "Cartoleria Rossi" and s.totale == Decimal("35")
    admin.post(f"/spesa/{sid}/stato", {"azione": "invia"})
    admin.post(f"/spesa/{sid}/ricevi", {f"ricevuto_{rid}": "6"})
    s = get(app, OrdineSpesa, sid)
    assert s.stato == StatoSpesa.PARZIALE
    assert get(app, Prodotto, pid).giacenza == 6
    with app.app_context():
        from app.magazzino import in_arrivo
        assert in_arrivo([pid])[pid] == 4
    admin.post(f"/spesa/{sid}/ricevi", {f"ricevuto_{rid}": "4"})
    assert get(app, OrdineSpesa, sid).stato == StatoSpesa.RICEVUTO
    assert get(app, Prodotto, pid).giacenza == 10


def test_ricezione_con_chiusura_anticipata(app, admin):
    pid = crea_prodotto(app, "Matite", "pz", "0")
    admin.post("/spesa/nuovo", {"prodotto_id": [str(pid)], "quantita": ["10"], "prezzo": [""]})
    with app.app_context():
        s = OrdineSpesa.query.one()
        sid, rid = s.id, s.righe[0].id
    admin.post(f"/spesa/{sid}/ricevi", {f"ricevuto_{rid}": "7", "chiudi": "1"})
    assert get(app, OrdineSpesa, sid).stato == StatoSpesa.RICEVUTO
    assert get(app, Prodotto, pid).giacenza == 7


# ------------------------------------------------------------------ funzioni nuove

def test_esportazioni_csv(app, admin):
    crea_prodotto(app, "Carta A4", "conf", "4", "5")
    r = admin.get("/magazzino/inventario.csv")
    testo = r.get_data(as_text=True)
    assert r.mimetype == "text/csv" and testo.startswith("﻿Prodotto;") and "Carta A4;;conf;4;5" in testo
    assert "Carta A4" in admin.get("/magazzino/movimenti.csv").get_data(as_text=True)
    admin.post("/spesa/da-sotto-scorta")
    with app.app_context():
        sid = OrdineSpesa.query.one().id
    assert "Carta A4;;6;conf" in admin.get(f"/spesa/{sid}/ordine.csv").get_data(as_text=True)
    assert "ORDINE DI ACQUISTO" in admin.get(f"/spesa/{sid}/stampa").get_data(as_text=True)


def test_ripeti_ordine(app, docente, unita):
    pid = crea_prodotto(app, "Carta A4", "conf", "4")
    oid = ordina(docente, [(pid, "2", "", ""), ("altro", "1", "Lavagnetta", unita["pz"])], note="Lab")
    html = docente.get(f"/ordini/nuovo?da={oid}").get_data(as_text=True)
    assert '"prodotto_id": "altro"' in html and "Lavagnetta" in html and ">Lab</textarea>" in html


def test_fornitori(app, admin):
    r = admin.post("/spesa/fornitori/nuovo", {"nome": "Ditta Bianchi", "email": "ordini@bianchi.it"})
    assert r.status_code == 302
    r = admin.post("/spesa/fornitori/nuovo", {"nome": "ditta bianchi"}, follow_redirects=True)
    assert "Esiste già" in r.get_data(as_text=True)
    with app.app_context():
        assert Fornitore.query.count() == 1


def test_blocco_login_dopo_tentativi(app):
    c = Client(app)
    for _ in range(5):
        c.post("/login", {"email": "doc@scuola.it", "password": "sbagliata"})
    r = c.post("/login", {"email": "doc@scuola.it", "password": "password-doc"})
    assert r.status_code == 429 and "Troppi tentativi" in r.get_data(as_text=True)


def test_csrf_obbligatorio(app, admin):
    r = admin.c.post("/spesa/da-sotto-scorta", data={})
    assert r.status_code == 400


def test_notifiche_disattivabili(app, docente):
    docente.post("/profilo", {"azione": "notifiche"})
    with app.app_context():
        assert Utente.query.filter_by(email="doc@scuola.it").one().notifiche_email is False


# ------------------------------------------------------------------ migrazioni

def test_aggiornamento_da_database_vecchio(app):
    """Un database della prima versione (Float, senza movimenti né fornitori) viene aggiornato."""
    with app.app_context():
        downgrade(directory=CARTELLA_MIGRAZIONI, revision="0001")
        db.session.execute(text("INSERT INTO prodotti (nome, descrizione, categoria, unita_id, giacenza,"
                                " scorta_minima, attivo, creato_il) VALUES ('Vecchio', '', '', 1, 2.5, 0, 1,"
                                " '2025-01-01 00:00:00')"))
        db.session.execute(text("INSERT INTO ordini_spesa (fornitore, note, stato, creato_da_id, creato_il)"
                                " VALUES ('Ditta Verdi', '', 'ricevuto', 1, '2025-01-01 00:00:00')"))
        db.session.execute(text("INSERT INTO righe_spesa (ordine_spesa_id, prodotto_id, quantita)"
                                " VALUES (1, 1, 3)"))
        db.session.commit()
        upgrade(directory=CARTELLA_MIGRAZIONI)
        db.session.expire_all()
        p = Prodotto.query.filter_by(nome="Vecchio").one()
        assert p.giacenza == Decimal("2.5")
        assert p.movimenti.one().tipo == "iniziale"
        s = db.session.get(OrdineSpesa, 1)
        assert s.fornitore.nome == "Ditta Verdi" and s.righe[0].quantita_ricevuta == 3


def test_ip_reale_dietro_proxy(tmp_path):
    """Con TRUST_PROXY il blocco login usa l'IP vero: un utente non blocca tutti gli altri."""
    from app import create_app
    app = create_app({"TESTING": True, "TRUST_PROXY": 1,
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'p.db'}"})
    from app.utils import limitatore_login
    limitatore_login._falliti.clear()
    c = app.test_client()
    c.get("/login", headers={"X-Forwarded-For": "203.0.113.7"})
    with c.session_transaction() as s:
        token = s.get("_csrf")
    for _ in range(5):
        c.post("/login", data={"_csrf": token, "email": "x@y.it", "password": "no"},
               headers={"X-Forwarded-For": "203.0.113.7"})
    assert limitatore_login.bloccato("ip:203.0.113.7")
    assert not limitatore_login.bloccato("ip:127.0.0.1")


def test_ip_reale_pythonanywhere(tmp_path):
    """PythonAnywhere passa l'IP del visitatore in X-Real-IP."""
    from app import create_app
    from app.utils import limitatore_login
    app = create_app({"TESTING": True, "TRUST_PROXY": 1,
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'p.db'}"})
    limitatore_login._falliti.clear()
    c = app.test_client()
    c.get("/login")
    with c.session_transaction() as s:
        token = s.get("_csrf")
    for _ in range(5):
        c.post("/login", data={"_csrf": token, "email": "x@y.it", "password": "no"},
               headers={"X-Real-IP": "198.51.100.9"})
    assert limitatore_login.bloccato("ip:198.51.100.9")
    assert not limitatore_login.bloccato("ip:127.0.0.1")
