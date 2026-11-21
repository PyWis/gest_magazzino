from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from ..magazzino import (GiacenzaInsufficiente, collega_riga, da_comprare, domanda_aperta, in_arrivo,
                         muovi)
from ..models import (Ordine, OrdineSpesa, Prodotto, RigaOrdine, RigaSpesa, StatoOrdine,
                      TipoMovimento, Unita, Utente, db)
from ..utils import (PER_PAGINA, admin_richiesto, docente_richiesto, fmt_qta, notifica_docente,
                     pagina, parse_qta)

bp = Blueprint("ordini", __name__, url_prefix="/ordini")


# ---------------------------------------------------------------- lato docente

@bp.route("/miei")
@docente_richiesto
def miei():
    ordini = (Ordine.query.filter_by(docente_id=current_user.id)
              .order_by(Ordine.creato_il.desc()).paginate(page=pagina(), per_page=PER_PAGINA))
    return render_template("ordini/miei.html", ordini=ordini)


@bp.route("/nuovo", methods=["GET", "POST"])
@docente_richiesto
def nuovo():
    prodotti = Prodotto.query.filter_by(attivo=True).order_by(Prodotto.categoria, Prodotto.nome).all()
    unita = Unita.query.order_by(Unita.nome).all()
    righe_input = []
    note = ""

    # "Ripeti ordine": precompila il modulo con le righe di un ordine precedente
    da = request.args.get("da", "")
    if request.method == "GET" and da.isdigit():
        vecchio = db.session.get(Ordine, int(da))
        if vecchio and vecchio.docente_id == current_user.id:
            for r in vecchio.righe:
                if r.prodotto and r.prodotto.attivo:
                    righe_input.append({"prodotto_id": str(r.prodotto_id), "descrizione": "",
                                        "unita_id": "", "quantita": fmt_qta(r.quantita_richiesta)})
                elif not r.prodotto:
                    righe_input.append({"prodotto_id": "altro", "descrizione": r.descrizione_libera,
                                        "unita_id": str(r.unita_id),
                                        "quantita": fmt_qta(r.quantita_richiesta)})
            note = vecchio.note

    if request.method == "POST":
        f = request.form
        pids, descr = f.getlist("prodotto_id"), f.getlist("descrizione")
        uids, qtas = f.getlist("unita_id"), f.getlist("quantita")
        note = f.get("note", "").strip()
        if not (len(pids) == len(descr) == len(uids) == len(qtas)):
            abort(400)

        errori, righe = [], []
        for i, (pid, d, uid, qs) in enumerate(zip(pids, descr, uids, qtas), start=1):
            pid, d, uid, qs = pid.strip(), d.strip(), uid.strip(), qs.strip()
            righe_input.append({"prodotto_id": pid, "descrizione": d, "unita_id": uid, "quantita": qs})
            if not pid and not qs and not d:
                continue  # riga vuota
            q = parse_qta(qs)
            if q is None or q <= 0:
                errori.append(f"Riga {i}: inserisci una quantità maggiore di zero.")
                continue
            if pid == "altro":
                u = db.session.get(Unita, int(uid)) if uid.isdigit() else None
                if not d:
                    errori.append(f"Riga {i}: descrivi l'articolo richiesto.")
                elif not u:
                    errori.append(f"Riga {i}: scegli l'unità di misura.")
                else:
                    righe.append(RigaOrdine(descrizione_libera=d[:255], richiesta_extra=True,
                                            unita=u, quantita_richiesta=q))
            elif pid.isdigit():
                p = db.session.get(Prodotto, int(pid))
                if not p or not p.attivo:
                    errori.append(f"Riga {i}: prodotto non disponibile.")
                else:
                    righe.append(RigaOrdine(prodotto=p, unita_id=p.unita_id, quantita_richiesta=q))
            else:
                errori.append(f"Riga {i}: seleziona un articolo.")

        if not righe and not errori:
            errori.append("Aggiungi almeno un articolo all'ordine.")
        if not errori:
            ordine = Ordine(docente_id=current_user.id, note=note, righe=righe)
            db.session.add(ordine)
            db.session.commit()
            flash(f"Ordine #{ordine.id} inviato.", "success")
            return redirect(url_for("ordini.dettaglio", oid=ordine.id))
        db.session.rollback()
        for e in errori:
            flash(e, "danger")

    return render_template("ordini/nuovo.html", prodotti=prodotti, unita=unita,
                           righe_input=righe_input, note=note)


@bp.route("/<int:oid>/annulla", methods=["POST"])
@docente_richiesto
def annulla(oid):
    ordine = db.get_or_404(Ordine, oid)
    if ordine.docente_id != current_user.id:
        abort(403)
    if ordine.stato != StatoOrdine.IN_ATTESA:
        flash("Puoi annullare solo ordini non ancora presi in carico.", "warning")
    else:
        ordine.stato = StatoOrdine.ANNULLATO
        db.session.commit()
        flash("Ordine annullato.", "info")
    return redirect(url_for("ordini.dettaglio", oid=oid))


# ---------------------------------------------------------------- comune

@bp.route("/<int:oid>")
@login_required
def dettaglio(oid):
    ordine = db.get_or_404(Ordine, oid)
    if not current_user.is_admin and ordine.docente_id != current_user.id:
        abort(403)
    prodotti = []
    if current_user.is_admin and any(r.prodotto is None for r in ordine.righe):
        prodotti = Prodotto.query.filter_by(attivo=True).order_by(Prodotto.nome).all()
    return render_template("ordini/dettaglio.html", ordine=ordine, prodotti=prodotti)


# ---------------------------------------------------------------- lato admin

@bp.route("/")
@admin_richiesto
def index():
    filtro = request.args.get("stato", "aperti")
    cerca = request.args.get("q", "").strip()
    query = Ordine.query.join(Ordine.docente)
    if filtro == "aperti":
        query = query.filter(Ordine.stato.in_(StatoOrdine.APERTI))
    elif filtro in StatoOrdine.ETICHETTE:
        query = query.filter(Ordine.stato == filtro)
    if cerca:
        like = f"%{cerca}%"
        cond = [Utente.nome.ilike(like), Utente.cognome.ilike(like), Utente.email.ilike(like)]
        if cerca.lstrip("#").isdigit():
            cond.append(Ordine.id == int(cerca.lstrip("#")))
        query = query.filter(or_(*cond))
    ordini = query.order_by(Ordine.creato_il.desc()).paginate(page=pagina(), per_page=PER_PAGINA)
    return render_template("ordini/index.html", ordini=ordini, filtro=filtro, q=cerca)


@bp.route("/<int:oid>/gestisci", methods=["POST"])
@admin_richiesto
def gestisci(oid):
    """Un unico form per: collegare richieste "Altro" a prodotti, registrare
    consegne (scaricando il magazzino), chiudere o rifiutare l'ordine."""
    ordine = db.get_or_404(Ordine, oid)
    if not ordine.aperto:
        flash("L'ordine non è più aperto.", "warning")
        return redirect(url_for("ordini.dettaglio", oid=oid))

    stato_prima = ordine.stato
    azione = request.form.get("azione", "consegna")
    ordine.nota_admin = request.form.get("nota_admin", "").strip()
    ordine.gestito_da_id = current_user.id

    if azione == "rifiuta":
        if ordine.qualcosa_consegnato:
            flash("Hai già consegnato parte del materiale: usa «Chiudi ordine».", "warning")
            return redirect(url_for("ordini.dettaglio", oid=oid))
        ordine.stato = StatoOrdine.RIFIUTATO
        db.session.commit()
        notifica_docente(ordine)
        flash(f"Ordine #{oid} rifiutato.", "info")
        return redirect(url_for("ordini.index"))

    errori = []

    # 1) collegamento di richieste "Altro" a prodotti esistenti, con conversione dell'unità
    for riga in ordine.righe:
        if riga.prodotto is None:
            pid = request.form.get(f"collega_{riga.id}", "")
            if pid.isdigit():
                p = db.session.get(Prodotto, int(pid))
                if p:
                    manuale = request.form.get(f"qta_collega_{riga.id}", "").strip()
                    q_man = parse_qta(manuale) if manuale else None
                    if manuale and q_man is None:
                        errori.append(f"«{riga.nome}»: quantità convertita non valida.")
                    elif (err := collega_riga(riga, p, q_man)):
                        errori.append(err)

    # 2) consegne: prima si valida tutto, poi si applica
    consegne = []
    for riga in ordine.righe:
        campo = request.form.get(f"consegna_{riga.id}")
        if campo is None or riga.prodotto is None or riga.completa:
            continue
        q = parse_qta(campo or "0")
        if q is None or q < 0:
            errori.append(f"«{riga.nome}»: quantità non valida.")
        elif q > riga.mancante:
            errori.append(f"«{riga.nome}»: stai consegnando più di quanto manca.")
        elif q > riga.prodotto.giacenza:
            errori.append(f"«{riga.nome}»: in magazzino ce ne sono solo "
                          f"{fmt_qta(riga.prodotto.giacenza)} {riga.prodotto.unita.simbolo}.")
        elif q > 0:
            consegne.append((riga, q))

    if errori:
        db.session.rollback()
        for e in errori:
            flash(e, "danger")
        return redirect(url_for("ordini.dettaglio", oid=oid))

    try:
        for riga, q in consegne:
            muovi(riga.prodotto, -q, TipoMovimento.SCARICO, ordine=ordine,
                  nota=f"Consegna a {ordine.docente.nome_completo}")
            riga.quantita_evasa = riga.quantita_evasa + q
    except GiacenzaInsufficiente as e:
        db.session.rollback()
        flash(f"«{e}»: la giacenza è cambiata nel frattempo e non basta più. Ricontrolla le quantità.",
              "danger")
        return redirect(url_for("ordini.dettaglio", oid=oid))
    ordine.aggiorna_stato()

    if azione == "chiudi" and ordine.aperto:
        ordine.stato = StatoOrdine.CHIUSO
    db.session.commit()

    if ordine.stato != stato_prima:
        notifica_docente(ordine)
    if consegne:
        flash(f"Consegna registrata ({len(consegne)} articoli). Magazzino aggiornato.", "success")
    if ordine.stato == StatoOrdine.EVASO:
        flash(f"Ordine #{oid} completamente evaso.", "success")
    elif ordine.stato == StatoOrdine.CHIUSO:
        flash(f"Ordine #{oid} chiuso.", "info")
    elif not consegne:
        flash("Modifiche salvate.", "info")
    return redirect(url_for("ordini.dettaglio", oid=oid))


@bp.route("/<int:oid>/ordine-spesa", methods=["POST"])
@admin_richiesto
def crea_spesa(oid):
    """Bozza di ordine di spesa con ciò che serve per evadere l'ordine. Tiene conto di tutta
    la domanda aperta per quei prodotti e di quanto è già in arrivo da altri ordini di spesa."""
    ordine = db.get_or_404(Ordine, oid)
    prodotti, senza_prodotto = {}, 0
    for riga in ordine.righe:
        if riga.completa:
            continue
        if riga.prodotto is None:
            senza_prodotto += 1
        else:
            prodotti[riga.prodotto.id] = riga.prodotto

    domanda, arrivo = domanda_aperta(list(prodotti)), in_arrivo(list(prodotti))
    righe, coperti = [], []
    for pid, prodotto in prodotti.items():
        q = da_comprare(prodotto, domanda[pid], arrivo[pid])
        if q > 0:
            righe.append(RigaSpesa(prodotto=prodotto, quantita=q))
        elif arrivo[pid] > 0 and prodotto.giacenza < domanda[pid]:
            coperti.append(prodotto.nome)

    if senza_prodotto:
        flash(f"{senza_prodotto} richieste «Altro» non sono ancora collegate a un prodotto: "
              "crea o collega il prodotto per poterle includere.", "warning")
    if coperti:
        flash("Già in arrivo con altri ordini di spesa: " + ", ".join(coperti) + ".", "info")
    if not righe:
        flash("Non serve comprare nulla per questo ordine.", "info")
        return redirect(url_for("ordini.dettaglio", oid=oid))

    spesa = OrdineSpesa(creato_da_id=current_user.id, ordine_origine=ordine, righe=righe,
                        note=f"Per ordine #{ordine.id} di {ordine.docente.nome_completo}")
    db.session.add(spesa)
    db.session.commit()
    flash(f"Bozza di ordine di spesa #{spesa.id} creata: controllala e completala.", "success")
    return redirect(url_for("spesa.modifica", sid=spesa.id))
