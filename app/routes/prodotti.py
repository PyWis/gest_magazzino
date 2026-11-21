from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_

from ..magazzino import (GiacenzaCambiata, collega_riga, domanda_aperta, in_arrivo, muovi,
                         rettifica)
from ..models import (GruppoUnita, Movimento, Prodotto, RigaOrdine, TipoMovimento, Unita,
                      db)
from ..utils import (PER_PAGINA, admin_richiesto, csv_response, fmt_data, fmt_qta, pagina,
                     parse_qta)

bp = Blueprint("prodotti", __name__, url_prefix="/magazzino")


def _query_prodotti(q, filtro, categoria):
    query = Prodotto.query.filter_by(attivo=(filtro != "disattivati"))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Prodotto.nome.ilike(like), Prodotto.categoria.ilike(like),
                                 Prodotto.descrizione.ilike(like)))
    if categoria:
        query = query.filter(Prodotto.categoria == categoria)
    if filtro == "sotto_scorta":
        query = query.filter(Prodotto.scorta_minima > 0, Prodotto.giacenza <= Prodotto.scorta_minima)
    elif filtro == "esauriti":
        query = query.filter(Prodotto.giacenza <= 0)
    return query.order_by(Prodotto.categoria, Prodotto.nome)


@bp.route("/")
@admin_richiesto
def index():
    q = request.args.get("q", "").strip()
    filtro = request.args.get("filtro", "")
    categoria = request.args.get("categoria", "")
    prodotti = _query_prodotti(q, filtro, categoria).paginate(page=pagina(), per_page=50)
    ids = [p.id for p in prodotti.items]
    n_sotto_scorta = _query_prodotti("", "sotto_scorta", "").count()
    return render_template("prodotti/index.html", prodotti=prodotti, q=q, filtro=filtro,
                           categoria=categoria, categorie=_categorie(),
                           n_sotto_scorta=n_sotto_scorta,
                           arrivo=in_arrivo(ids), domanda=domanda_aperta(ids))


@bp.route("/inventario.csv")
@admin_richiesto
def esporta_inventario():
    prodotti = _query_prodotti(request.args.get("q", "").strip(), request.args.get("filtro", ""),
                               request.args.get("categoria", "")).all()
    ids = [p.id for p in prodotti]
    arrivo, domanda = in_arrivo(ids), domanda_aperta(ids)
    return csv_response(
        "inventario.csv",
        ["Prodotto", "Categoria", "Unità", "Giacenza", "Scorta minima", "Da consegnare ai docenti",
         "In arrivo dai fornitori", "Sotto scorta"],
        [[p.nome, p.categoria, p.unita.simbolo, fmt_qta(p.giacenza), fmt_qta(p.scorta_minima),
          fmt_qta(domanda[p.id]), fmt_qta(arrivo[p.id]), "sì" if p.sotto_scorta else ""]
         for p in prodotti])


def _categorie():
    righe = db.session.query(Prodotto.categoria).filter(Prodotto.categoria != "").distinct()
    return sorted(r[0] for r in righe)


def _salva(prodotto, nuovo):
    """Legge il form. La giacenza si imposta solo alla creazione: dopo, si cambia
    esclusivamente con movimenti (consegne, ricezioni, rettifiche)."""
    errori = []
    nome = request.form.get("nome", "").strip()
    unita_id = request.form.get("unita_id", "")
    giacenza = parse_qta(request.form.get("giacenza") or "0") if nuovo else None
    scorta = parse_qta(request.form.get("scorta_minima") or "0")
    unita = db.session.get(Unita, int(unita_id)) if unita_id.isdigit() else None

    if not nome:
        errori.append("Il nome è obbligatorio.")
    elif (Prodotto.query.filter(func.lower(Prodotto.nome) == nome.lower(),
                                Prodotto.id != (prodotto.id or 0)).first()):
        errori.append("Esiste già un prodotto con questo nome.")
    if not unita:
        errori.append("Seleziona l'unità di misura.")
    elif not nuovo and unita.id != prodotto.unita_id and (
            RigaOrdine.query.filter_by(prodotto_id=prodotto.id).first() or prodotto.giacenza != 0):
        errori.append("Non puoi cambiare l'unità di misura di un prodotto già in uso o con giacenza.")
    if nuovo and (giacenza is None or giacenza < 0):
        errori.append("Giacenza non valida.")
    if scorta is None or scorta < 0:
        errori.append("Scorta minima non valida.")

    if not errori:
        prodotto.nome = nome
        prodotto.descrizione = request.form.get("descrizione", "").strip()
        prodotto.categoria = request.form.get("categoria", "").strip()
        prodotto.unita = unita
        prodotto.scorta_minima = scorta
        if not nuovo:
            prodotto.attivo = request.form.get("attivo") == "1"
    return errori, giacenza


@bp.route("/nuovo", methods=["GET", "POST"])
@admin_richiesto
def nuovo():
    """Nuovo prodotto. Con ?da_riga=ID lo crea da una richiesta "Altro" di un docente
    e collega automaticamente quella riga d'ordine al prodotto."""
    riga = None
    da_riga = request.args.get("da_riga", "")
    if da_riga.isdigit():
        riga = db.session.get(RigaOrdine, int(da_riga))
        if riga and (riga.prodotto_id or not riga.ordine.aperto):
            riga = None

    prodotto = Prodotto(giacenza=0, scorta_minima=0, attivo=True)
    if riga and request.method == "GET":
        prodotto.nome = riga.descrizione_libera
        prodotto.unita_id = riga.unita_id

    if request.method == "POST":
        errori, giacenza = _salva(prodotto, nuovo=True)
        if not errori and riga:
            manuale = request.form.get("qta_riga", "").strip()
            q_man = parse_qta(manuale) if manuale else None
            if manuale and q_man is None:
                errori.append("Quantità convertita non valida.")
            else:
                err = collega_riga(riga, prodotto, q_man)
                if err:
                    errori.append(err)
        if not errori:
            prodotto.giacenza = 0
            db.session.add(prodotto)
            db.session.flush()
            if giacenza:
                muovi(prodotto, giacenza, TipoMovimento.INIZIALE, nota="Giacenza iniziale")
            db.session.commit()
            flash(f"Prodotto «{prodotto.nome}» creato.", "success")
            if riga:
                return redirect(url_for("ordini.dettaglio", oid=riga.ordine_id))
            return redirect(url_for("prodotti.scheda", pid=prodotto.id))
        db.session.rollback()
        for e in errori:
            flash(e, "danger")

    return render_template("prodotti/form.html", prodotto=prodotto, nuovo=True, riga=riga,
                           unita=Unita.query.order_by(Unita.nome).all(), categorie=_categorie())


@bp.route("/<int:pid>")
@admin_richiesto
def scheda(pid):
    prodotto = db.get_or_404(Prodotto, pid)
    movimenti = (Movimento.query.filter_by(prodotto_id=pid).order_by(Movimento.id.desc())
                 .paginate(page=pagina(), per_page=PER_PAGINA))
    righe_aperte = [r for r in RigaOrdine.query.filter_by(prodotto_id=pid)
                    if r.ordine.aperto and not r.completa]
    return render_template("prodotti/scheda.html", prodotto=prodotto, movimenti=movimenti,
                           arrivo=in_arrivo([pid])[pid], domanda=domanda_aperta([pid])[pid],
                           righe_aperte=righe_aperte)


@bp.route("/<int:pid>/modifica", methods=["GET", "POST"])
@admin_richiesto
def modifica(pid):
    prodotto = db.get_or_404(Prodotto, pid)
    if request.method == "POST":
        errori, _ = _salva(prodotto, nuovo=False)
        if not errori:
            db.session.commit()
            flash("Prodotto aggiornato.", "success")
            return redirect(url_for("prodotti.scheda", pid=pid))
        db.session.rollback()
        for e in errori:
            flash(e, "danger")
    return render_template("prodotti/form.html", prodotto=prodotto, nuovo=False, riga=None,
                           unita=Unita.query.order_by(Unita.nome).all(), categorie=_categorie())


@bp.route("/<int:pid>/rettifica", methods=["POST"])
@admin_richiesto
def rettifica_giacenza(pid):
    """Correzione della giacenza dopo un conteggio (inventario), con motivo obbligatorio."""
    prodotto = db.get_or_404(Prodotto, pid)
    nuova = parse_qta(request.form.get("giacenza", ""))
    vista = parse_qta(request.form.get("giacenza_vista", ""))
    motivo = request.form.get("motivo", "").strip()
    if nuova is None or nuova < 0 or vista is None:
        flash("Indica una giacenza valida.", "danger")
    elif not motivo:
        flash("Indica il motivo della rettifica (es. inventario, merce rotta, scaduta...).", "danger")
    elif nuova == vista:
        flash("La giacenza indicata è uguale a quella attuale: nessuna modifica.", "info")
    else:
        try:
            rettifica(prodotto, nuova, vista, motivo)
            db.session.commit()
            flash(f"Giacenza di «{prodotto.nome}» rettificata a {fmt_qta(nuova)} "
                  f"{prodotto.unita.simbolo}.", "success")
        except GiacenzaCambiata:
            db.session.rollback()
            flash("Nel frattempo la giacenza è stata modificata da un'altra operazione "
                  "(consegna o ricezione). Controlla il valore aggiornato e riprova.", "warning")
    return redirect(url_for("prodotti.scheda", pid=pid))


# ---------------------------------------------------------------- registro movimenti

def _query_movimenti():
    query = Movimento.query.join(Movimento.prodotto)
    tipo = request.args.get("tipo", "")
    cerca = request.args.get("q", "").strip()
    if tipo in TipoMovimento.ETICHETTE:
        query = query.filter(Movimento.tipo == tipo)
    if cerca:
        query = query.filter(Prodotto.nome.ilike(f"%{cerca}%"))
    return query.order_by(Movimento.id.desc()), tipo, cerca


@bp.route("/movimenti")
@admin_richiesto
def movimenti():
    query, tipo, cerca = _query_movimenti()
    return render_template("prodotti/movimenti.html", tipo=tipo, q=cerca,
                           movimenti=query.paginate(page=pagina(), per_page=PER_PAGINA))


@bp.route("/movimenti.csv")
@admin_richiesto
def esporta_movimenti():
    query, _, _ = _query_movimenti()
    return csv_response(
        "movimenti.csv",
        ["Data", "Prodotto", "Tipo", "Quantità", "Unità", "Giacenza dopo", "Utente", "Riferimento", "Nota"],
        [[fmt_data(m.creato_il), m.prodotto.nome, m.tipo_label, fmt_qta(m.quantita),
          m.prodotto.unita.simbolo, fmt_qta(m.giacenza_dopo),
          m.utente.nome_completo if m.utente else "",
          (f"Ordine #{m.ordine_id}" if m.ordine_id else
           f"Ordine di spesa #{m.ordine_spesa_id}" if m.ordine_spesa_id else ""), m.nota]
         for m in query])


# ---------------------------------------------------------------- unità di misura

@bp.route("/unita", methods=["GET", "POST"])
@admin_richiesto
def unita():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        simbolo = request.form.get("simbolo", "").strip()
        gruppo = request.form.get("gruppo", "")
        fattore = parse_qta(request.form.get("fattore", ""), decimali=6) if gruppo else None
        if not nome or not simbolo:
            flash("Nome e simbolo sono obbligatori.", "danger")
        elif gruppo and gruppo not in GruppoUnita.ETICHETTE:
            flash("Tipo di grandezza non valido.", "danger")
        elif gruppo and (fattore is None or fattore <= 0):
            flash("Indica a quante unità base corrisponde (es. 1 ml = 0,001 l).", "danger")
        elif Unita.query.filter(func.lower(Unita.nome) == nome.lower()).first():
            flash("Esiste già un'unità con questo nome.", "danger")
        else:
            db.session.add(Unita(nome=nome[:50], simbolo=simbolo[:15], gruppo=gruppo, fattore=fattore))
            db.session.commit()
            flash("Unità aggiunta.", "success")
        return redirect(url_for("prodotti.unita"))

    elenco = Unita.query.order_by(Unita.gruppo, Unita.nome).all()
    in_uso = {u.id for u in elenco if Prodotto.query.filter_by(unita_id=u.id).first()
              or RigaOrdine.query.filter_by(unita_id=u.id).first()}
    return render_template("prodotti/unita.html", elenco=elenco, in_uso=in_uso, GruppoUnita=GruppoUnita)


@bp.route("/unita/<int:uid>/elimina", methods=["POST"])
@admin_richiesto
def elimina_unita(uid):
    u = db.get_or_404(Unita, uid)
    if Prodotto.query.filter_by(unita_id=uid).first() or RigaOrdine.query.filter_by(unita_id=uid).first():
        flash("Unità in uso: non può essere eliminata.", "danger")
    else:
        db.session.delete(u)
        db.session.commit()
        flash("Unità eliminata.", "success")
    return redirect(url_for("prodotti.unita"))
