from urllib.parse import quote

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func

from ..magazzino import da_comprare, domanda_aperta, in_arrivo, muovi
from ..models import (Fornitore, OrdineSpesa, Prodotto, RigaSpesa, StatoSpesa, TipoMovimento,
                      adesso, db)
from ..utils import (PER_PAGINA, admin_richiesto, csv_response, fmt_euro, fmt_qta, pagina,
                     parse_qta, valida_email)

bp = Blueprint("spesa", __name__, url_prefix="/spesa")


@bp.route("/")
@admin_richiesto
def index():
    filtro = request.args.get("stato", "")
    fid = request.args.get("fornitore", "")
    query = OrdineSpesa.query
    if filtro == "aperti":
        query = query.filter(OrdineSpesa.stato.in_(StatoSpesa.APERTI))
    elif filtro in StatoSpesa.ETICHETTE:
        query = query.filter_by(stato=filtro)
    if fid.isdigit():
        query = query.filter_by(fornitore_id=int(fid))
    spese = query.order_by(OrdineSpesa.creato_il.desc()).paginate(page=pagina(), per_page=PER_PAGINA)
    return render_template("spesa/index.html", spese=spese, filtro=filtro, fid=fid,
                           fornitori=Fornitore.query.order_by(Fornitore.nome).all())


def _leggi_form(spesa):
    f = request.form
    pids, qtas, prezzi = f.getlist("prodotto_id"), f.getlist("quantita"), f.getlist("prezzo")
    if not (len(pids) == len(qtas) == len(prezzi)):
        abort(400)
    errori, righe, righe_input = [], [], []
    for i, (pid, qs, ps) in enumerate(zip(pids, qtas, prezzi), start=1):
        pid, qs, ps = pid.strip(), qs.strip(), ps.strip()
        righe_input.append({"prodotto_id": pid, "quantita": qs, "prezzo": ps})
        if not pid and not qs and not ps:
            continue
        p = db.session.get(Prodotto, int(pid)) if pid.isdigit() else None
        q = parse_qta(qs)
        prezzo = parse_qta(ps, decimali=2) if ps else None
        if not p:
            errori.append(f"Riga {i}: seleziona un prodotto.")
        elif q is None or q <= 0:
            errori.append(f"Riga {i}: quantità non valida.")
        elif ps and (prezzo is None or prezzo < 0):
            errori.append(f"Riga {i}: prezzo non valido.")
        else:
            righe.append(RigaSpesa(prodotto=p, quantita=q, prezzo_unitario=prezzo))
    if not righe and not errori:
        errori.append("Aggiungi almeno un prodotto.")

    fornitore = None
    fid = f.get("fornitore_id", "").strip()
    nuovo_nome = f.get("fornitore_nuovo", "").strip()
    if fid == "nuovo":
        if not nuovo_nome:
            errori.append("Scrivi il nome del nuovo fornitore.")
        else:
            fornitore = (Fornitore.query.filter(func.lower(Fornitore.nome) == nuovo_nome.lower()).first()
                         or Fornitore(nome=nuovo_nome[:200]))
    elif fid.isdigit():
        fornitore = db.session.get(Fornitore, int(fid))

    if not errori:
        spesa.fornitore = fornitore
        spesa.note = f.get("note", "").strip()
        spesa.righe = righe
    return errori, righe_input


def _render_form(spesa, righe_input):
    prodotti = Prodotto.query.filter_by(attivo=True).order_by(Prodotto.nome).all()
    fornitori = Fornitore.query.filter_by(attivo=True).order_by(Fornitore.nome).all()
    if spesa.fornitore and spesa.fornitore not in fornitori:
        fornitori.append(spesa.fornitore)
    return render_template("spesa/form.html", spesa=spesa, prodotti=prodotti,
                           righe_input=righe_input, fornitori=fornitori)


@bp.route("/nuovo", methods=["GET", "POST"])
@admin_richiesto
def nuovo():
    spesa = OrdineSpesa(note="")
    righe_input = []
    if request.method == "POST":
        errori, righe_input = _leggi_form(spesa)
        if not errori:
            spesa.creato_da_id = current_user.id
            db.session.add(spesa)
            db.session.commit()
            flash(f"Ordine di spesa #{spesa.id} salvato come bozza.", "success")
            return redirect(url_for("spesa.dettaglio", sid=spesa.id))
        db.session.rollback()
        for e in errori:
            flash(e, "danger")
    return _render_form(spesa, righe_input)


@bp.route("/<int:sid>/modifica", methods=["GET", "POST"])
@admin_richiesto
def modifica(sid):
    spesa = db.get_or_404(OrdineSpesa, sid)
    if not spesa.modificabile:
        flash("Si possono modificare solo le bozze.", "warning")
        return redirect(url_for("spesa.dettaglio", sid=sid))
    righe_input = [{"prodotto_id": str(r.prodotto_id), "quantita": fmt_qta(r.quantita),
                    "prezzo": "" if r.prezzo_unitario is None else fmt_qta(r.prezzo_unitario)}
                   for r in spesa.righe]
    if request.method == "POST":
        errori, righe_input = _leggi_form(spesa)
        if not errori:
            db.session.commit()
            flash("Ordine di spesa aggiornato.", "success")
            return redirect(url_for("spesa.dettaglio", sid=sid))
        db.session.rollback()
        for e in errori:
            flash(e, "danger")
    return _render_form(spesa, righe_input)


def _mailto(spesa):
    if not (spesa.fornitore and spesa.fornitore.email):
        return None
    righe = "\n".join(f"- {r.prodotto.nome}: {fmt_qta(r.quantita)} {r.prodotto.unita.simbolo}"
                      for r in spesa.righe)
    testo = (f"Buongiorno,\n\nvi chiediamo di fornirci il seguente materiale:\n\n{righe}\n\n"
             f"{spesa.note + chr(10) + chr(10) if spesa.note else ''}Cordiali saluti")
    return (f"mailto:{spesa.fornitore.email}?subject={quote(f'Ordine n. {spesa.id}')}"
            f"&body={quote(testo)}")


@bp.route("/<int:sid>")
@admin_richiesto
def dettaglio(sid):
    spesa = db.get_or_404(OrdineSpesa, sid)
    return render_template("spesa/dettaglio.html", spesa=spesa, mailto=_mailto(spesa))


@bp.route("/<int:sid>/stampa")
@admin_richiesto
def stampa(sid):
    """Documento d'ordine pronto da stampare o salvare in PDF per il fornitore."""
    return render_template("spesa/stampa.html", spesa=db.get_or_404(OrdineSpesa, sid), oggi=adesso())


@bp.route("/<int:sid>/ordine.csv")
@admin_richiesto
def esporta(sid):
    spesa = db.get_or_404(OrdineSpesa, sid)
    righe = [[r.prodotto.nome, r.prodotto.categoria, fmt_qta(r.quantita), r.prodotto.unita.simbolo,
              fmt_qta(r.prezzo_unitario) if r.prezzo_unitario is not None else "",
              fmt_qta(r.subtotale) if r.subtotale is not None else ""] for r in spesa.righe]
    righe.append(["Totale", "", "", "", "", fmt_euro(spesa.totale).replace(" €", "")])
    return csv_response(f"ordine-spesa-{spesa.id}.csv",
                        ["Prodotto", "Categoria", "Quantità", "Unità", "Prezzo unitario €", "Subtotale €"],
                        righe)


@bp.route("/<int:sid>/stato", methods=["POST"])
@admin_richiesto
def cambia_stato(sid):
    spesa = db.get_or_404(OrdineSpesa, sid)
    azione = request.form.get("azione")

    if azione == "invia" and spesa.stato == StatoSpesa.BOZZA:
        spesa.stato, spesa.inviato_il = StatoSpesa.INVIATO, adesso()
        flash("Ordine segnato come inviato al fornitore.", "success")
    elif azione == "annulla" and spesa.stato in (StatoSpesa.BOZZA, StatoSpesa.INVIATO):
        spesa.stato = StatoSpesa.ANNULLATO
        flash("Ordine di spesa annullato.", "info")
    elif azione == "chiudi" and spesa.stato == StatoSpesa.PARZIALE:
        spesa.stato, spesa.ricevuto_il = StatoSpesa.RICEVUTO, adesso()
        flash("Ordine di spesa chiuso: la merce mancante non è più attesa.", "info")
    else:
        flash("Operazione non consentita in questo stato.", "warning")
    db.session.commit()
    return redirect(url_for("spesa.dettaglio", sid=sid))


@bp.route("/<int:sid>/ricevi", methods=["POST"])
@admin_richiesto
def ricevi(sid):
    """Registra la merce effettivamente arrivata (anche parziale) e carica il magazzino."""
    spesa = db.get_or_404(OrdineSpesa, sid)
    if not spesa.ricevibile:
        flash("Operazione non consentita in questo stato.", "warning")
        return redirect(url_for("spesa.dettaglio", sid=sid))

    arrivi, errori = [], []
    for r in spesa.righe:
        campo = request.form.get(f"ricevuto_{r.id}")
        if campo is None or r.da_ricevere <= 0:
            continue
        q = parse_qta(campo or "0")
        if q is None or q < 0:
            errori.append(f"«{r.prodotto.nome}»: quantità non valida.")
        elif q > 0:
            arrivi.append((r, q))
    if errori or not arrivi:
        for e in errori or ["Indica almeno una quantità ricevuta."]:
            flash(e, "danger")
        return redirect(url_for("spesa.dettaglio", sid=sid))

    for r, q in arrivi:
        muovi(r.prodotto, q, TipoMovimento.CARICO, ordine_spesa=spesa,
              nota=f"Ricevuto da {spesa.fornitore_nome or 'fornitore'}")
        r.quantita_ricevuta = (r.quantita_ricevuta or 0) + q

    if spesa.inviato_il is None:
        spesa.inviato_il = adesso()
    completo = all(r.da_ricevere <= 0 for r in spesa.righe)
    if completo or request.form.get("chiudi") == "1":
        spesa.stato, spesa.ricevuto_il = StatoSpesa.RICEVUTO, adesso()
    else:
        spesa.stato = StatoSpesa.PARZIALE
    db.session.commit()

    flash(f"Merce ricevuta ({len(arrivi)} prodotti): giacenze aggiornate.", "success")
    if spesa.stato == StatoSpesa.PARZIALE:
        flash("Manca ancora della merce: l'ordine resta aperto in attesa del resto.", "info")
    if spesa.ordine_origine and spesa.ordine_origine.aperto:
        flash(f"Ora puoi evadere l'ordine #{spesa.ordine_origine.id} "
              f"di {spesa.ordine_origine.docente.nome_completo}.", "info")
    return redirect(url_for("spesa.dettaglio", sid=sid))


@bp.route("/da-sotto-scorta", methods=["POST"])
@admin_richiesto
def da_sotto_scorta():
    """Bozza con i prodotti sotto scorta: porta la giacenza a 2× la scorta minima più quanto
    serve per gli ordini aperti, togliendo ciò che è già in arrivo da altri ordini di spesa."""
    prodotti = [p for p in Prodotto.query.filter_by(attivo=True).order_by(Prodotto.nome) if p.sotto_scorta]
    ids = [p.id for p in prodotti]
    domanda, arrivo = domanda_aperta(ids), in_arrivo(ids)
    righe, coperti = [], []
    for p in prodotti:
        q = da_comprare(p, domanda[p.id], arrivo[p.id], extra=2 * p.scorta_minima)
        if q > 0:
            righe.append(RigaSpesa(prodotto=p, quantita=q))
        else:
            coperti.append(p.nome)
    if coperti:
        flash("Già coperti da ordini di spesa in corso: " + ", ".join(coperti) + ".", "info")
    if not righe:
        if not prodotti:
            flash("Nessun prodotto sotto scorta.", "info")
        return redirect(url_for("prodotti.index"))
    spesa = OrdineSpesa(creato_da_id=current_user.id, righe=righe, note="Riordino prodotti sotto scorta")
    db.session.add(spesa)
    db.session.commit()
    flash(f"Bozza #{spesa.id} creata con {len(righe)} prodotti sotto scorta.", "success")
    return redirect(url_for("spesa.modifica", sid=spesa.id))


# ---------------------------------------------------------------- fornitori

@bp.route("/fornitori")
@admin_richiesto
def fornitori():
    elenco = Fornitore.query.order_by(Fornitore.attivo.desc(), Fornitore.nome).all()
    conteggi = dict(db.session.query(OrdineSpesa.fornitore_id, func.count())
                    .group_by(OrdineSpesa.fornitore_id))
    return render_template("spesa/fornitori.html", elenco=elenco, conteggi=conteggi)


@bp.route("/fornitori/nuovo", methods=["GET", "POST"])
@bp.route("/fornitori/<int:fid>", methods=["GET", "POST"])
@admin_richiesto
def fornitore(fid=None):
    f = db.get_or_404(Fornitore, fid) if fid else Fornitore(attivo=True, nome="", email="",
                                                              telefono="", note="")
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip()
        errori = []
        if not nome:
            errori.append("Il nome è obbligatorio.")
        elif Fornitore.query.filter(func.lower(Fornitore.nome) == nome.lower(),
                                    Fornitore.id != (f.id or 0)).first():
            errori.append("Esiste già un fornitore con questo nome.")
        if email and not valida_email(email):
            errori.append("Email non valida.")
        if not errori:
            f.nome, f.email = nome[:200], email
            f.telefono = request.form.get("telefono", "").strip()[:50]
            f.note = request.form.get("note", "").strip()
            if fid:
                f.attivo = request.form.get("attivo") == "1"
            db.session.add(f)
            db.session.commit()
            flash("Fornitore salvato.", "success")
            return redirect(url_for("spesa.fornitori"))
        for e in errori:
            flash(e, "danger")
    return render_template("spesa/fornitore_form.html", f=f, nuovo=fid is None)
