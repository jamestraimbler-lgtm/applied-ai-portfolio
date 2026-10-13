"""
app.py — FinanZen lokale webapplicatie
Start met: python app.py  (of via Start FinanZen.command)
Bereikbaar op: http://localhost:5757
"""
import os, io, json
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, send_file, jsonify, abort)
import security, database as db, export, documentintake as intake, rekenkern

# ── App-configuratie ─────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.secret_key = security.get_flask_secret()
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024   # max 25 MB per upload
app.config['TEMPLATES_AUTO_RELOAD'] = True            # sjablonen direct verversen

INACTIVITEIT_SECONDEN = 15 * 60   # 15 minuten


# ── Hulpfuncties sessie ──────────────────────────────────────────────────────

def _update_activiteit():
    session['last_activity'] = datetime.now().isoformat()


def _sessie_verlopen() -> bool:
    la = session.get('last_activity')
    if not la:
        return True
    return (datetime.now() - datetime.fromisoformat(la)).total_seconds() \
           > INACTIVITEIT_SECONDEN


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not security.is_setup_done():
            return redirect(url_for('setup'))
        if not session.get('logged_in') or not security.is_unlocked():
            session.clear()
            flash('Log in om door te gaan.', 'info')
            return redirect(url_for('login', next=request.path))
        if _sessie_verlopen():
            security.lock()
            session.clear()
            flash('U bent automatisch uitgelogd na 15 minuten inactiviteit.', 'warning')
            return redirect(url_for('login'))
        _update_activiteit()
        return f(*args, **kwargs)
    return wrapper


# ── Eerste start / setup ──────────────────────────────────────────────────────

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if security.is_setup_done():
        return redirect(url_for('login'))
    if request.method == 'POST':
        pw  = request.form.get('wachtwoord', '')
        pw2 = request.form.get('wachtwoord2', '')
        if len(pw) < 8:
            flash('Wachtwoord moet minimaal 8 tekens zijn.', 'fout')
        elif pw != pw2:
            flash('Wachtwoorden komen niet overeen.', 'fout')
        else:
            security.setup_password(pw)
            db.init_db()
            # Herlees secret key nu die is aangemaakt
            app.secret_key = security.get_flask_secret()
            flash('Wachtwoord ingesteld. U kunt nu inloggen.', 'ok')
            db.logboek_schrijven(None, 'Applicatie ingesteld')
            return redirect(url_for('login'))
    return render_template('setup.html')


# ── Login / logout ────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if not security.is_setup_done():
        return redirect(url_for('setup'))
    if session.get('logged_in') and security.is_unlocked() and not _sessie_verlopen():
        return redirect(url_for('dossiers'))
    if request.method == 'POST':
        pw = request.form.get('wachtwoord', '')
        if security.unlock(pw):
            session['logged_in'] = True
            _update_activiteit()
            db.logboek_schrijven(None, 'Ingelogd')
            nxt = request.args.get('next') or url_for('dossiers')
            return redirect(nxt)
        else:
            flash('Ongeldig wachtwoord.', 'fout')
    return render_template('login.html')


@app.route('/uitloggen')
def uitloggen():
    db.logboek_schrijven(None, 'Uitgelogd')
    security.lock()
    session.clear()
    flash('U bent uitgelogd en de applicatie is vergrendeld.', 'info')
    return redirect(url_for('login'))


# ── API: activiteits-ping voor auto-lock ─────────────────────────────────────

@app.route('/api/ping', methods=['GET', 'POST'])
def api_ping():
    if not session.get('logged_in') or not security.is_unlocked():
        return jsonify(status='vergrendeld'), 401
    if _sessie_verlopen():
        security.lock()
        session.clear()
        return jsonify(status='verlopen'), 401
    _update_activiteit()
    return jsonify(status='actief',
                   verloopt_over=int(INACTIVITEIT_SECONDEN -
                       (datetime.now() - datetime.fromisoformat(
                        session['last_activity'])).total_seconds()))


# ── Dossieroverzicht ──────────────────────────────────────────────────────────

@app.route('/')
def index():
    if not security.is_setup_done():
        return redirect(url_for('setup'))
    return redirect(url_for('dossiers'))


@app.route('/dossiers')
@login_required
def dossiers():
    zaken  = db.alle_zaken_ophalen()
    zoek   = request.args.get('zoek', '').lower()
    status = request.args.get('status', '')
    if zoek:
        zaken = [z for z in zaken if zoek in (z['naam1'] or '').lower()
                                   or zoek in (z['naam2'] or '').lower()
                                   or zoek in (z['omschrijving'] or '').lower()]
    if status:
        zaken = [z for z in zaken if z['status'] == status]
    return render_template('dossiers.html', zaken=zaken,
                           soorten=db.ZAAK_SOORTEN, statussen=db.ZAAK_STATUSSEN,
                           zoek=zoek, status_filter=status)


# ── Nieuw dossier ─────────────────────────────────────────────────────────────

@app.route('/dossiers/nieuw', methods=['GET', 'POST'])
@login_required
def nieuw_dossier():
    if request.method == 'POST':
        f = request.form
        # Aanvrager 1
        k1_data = dict(
            voornaam=f.get('v1_voornaam','').strip(),
            tussenvoegsel=f.get('v1_tussenvoegsel','').strip() or None,
            achternaam=f.get('v1_achternaam','').strip(),
            geboortedatum=f.get('v1_geboortedatum','').strip() or None,
            email=f.get('v1_email','').strip() or None,
            telefoon=f.get('v1_telefoon','').strip() or None,
            adres=f.get('v1_adres','').strip() or None,
            postcode=f.get('v1_postcode','').strip() or None,
            woonplaats=f.get('v1_woonplaats','').strip() or None,
            bsn_enc=None,
        )
        if not k1_data['voornaam'] or not k1_data['achternaam']:
            flash('Voornaam en achternaam van aanvrager 1 zijn verplicht.', 'fout')
            return render_template('dossier_form.html', soorten=db.ZAAK_SOORTEN, form=f)

        k1_id = db.klant_aanmaken(k1_data)

        # Aanvrager 2 (optioneel)
        k2_id = None
        if f.get('heeft_partner') == '1':
            k2_data = dict(
                voornaam=f.get('v2_voornaam','').strip(),
                tussenvoegsel=f.get('v2_tussenvoegsel','').strip() or None,
                achternaam=f.get('v2_achternaam','').strip(),
                geboortedatum=f.get('v2_geboortedatum','').strip() or None,
                email=f.get('v2_email','').strip() or None,
                telefoon=f.get('v2_telefoon','').strip() or None,
                adres=f.get('v2_adres','').strip() or None,
                postcode=f.get('v2_postcode','').strip() or None,
                woonplaats=f.get('v2_woonplaats','').strip() or None,
                bsn_enc=None,
            )
            if k2_data['voornaam'] and k2_data['achternaam']:
                k2_id = db.klant_aanmaken(k2_data)

        zaak_id = db.zaak_aanmaken(
            k1_id, k2_id,
            f.get('soort','aankoop_bestaand'),
            f.get('omschrijving','').strip() or None,
        )
        flash('Dossier aangemaakt.', 'ok')
        return redirect(url_for('dossier_detail', zaak_id=zaak_id))

    return render_template('dossier_form.html', soorten=db.ZAAK_SOORTEN, form={})


# ── Dossier detail ────────────────────────────────────────────────────────────

@app.route('/dossiers/<int:zaak_id>')
@login_required
def dossier_detail(zaak_id):
    zaak = db.zaak_ophalen(zaak_id)
    if not zaak:
        abort(404)
    k1      = db.klant_ophalen(zaak['aanvrager1_id'])
    k2      = db.klant_ophalen(zaak['aanvrager2_id']) if zaak['aanvrager2_id'] else None
    stukken = db.stukken_ophalen(zaak_id)
    taken   = db.taken_ophalen(zaak_id)
    notities= db.notities_ophalen(zaak_id)
    signaleringen = db.signaleringen_ophalen(zaak_id)
    # Document per stuk (laatste upload) voor de stukkenlijst
    docs = {}
    for s in stukken:
        d = db.document_van_stuk(s['id'])
        if d:
            docs[s['id']] = d
    return render_template('dossier_detail.html',
                           zaak=zaak, k1=k1, k2=k2,
                           stukken=stukken, taken=taken, notities=notities,
                           signaleringen=signaleringen, docs=docs,
                           stuk_statussen=db.STUK_STATUSSEN,
                           soorten=db.ZAAK_SOORTEN, statussen=db.ZAAK_STATUSSEN)


# ── Dossier bewerken ──────────────────────────────────────────────────────────

@app.route('/dossiers/<int:zaak_id>/bewerken', methods=['GET', 'POST'])
@login_required
def dossier_bewerken(zaak_id):
    zaak = db.zaak_ophalen(zaak_id)
    if not zaak:
        abort(404)
    k1 = db.klant_ophalen(zaak['aanvrager1_id'])
    k2 = db.klant_ophalen(zaak['aanvrager2_id']) if zaak['aanvrager2_id'] else None

    if request.method == 'POST':
        f = request.form
        # Klant 1 bijwerken
        db.klant_bijwerken(zaak['aanvrager1_id'], dict(
            voornaam=f.get('v1_voornaam','').strip(),
            tussenvoegsel=f.get('v1_tussenvoegsel','').strip() or None,
            achternaam=f.get('v1_achternaam','').strip(),
            geboortedatum=f.get('v1_geboortedatum','').strip() or None,
            email=f.get('v1_email','').strip() or None,
            telefoon=f.get('v1_telefoon','').strip() or None,
            adres=f.get('v1_adres','').strip() or None,
            postcode=f.get('v1_postcode','').strip() or None,
            woonplaats=f.get('v1_woonplaats','').strip() or None,
            bsn_enc=None,
        ))
        if k2:
            db.klant_bijwerken(zaak['aanvrager2_id'], dict(
                voornaam=f.get('v2_voornaam','').strip(),
                tussenvoegsel=f.get('v2_tussenvoegsel','').strip() or None,
                achternaam=f.get('v2_achternaam','').strip(),
                geboortedatum=f.get('v2_geboortedatum','').strip() or None,
                email=f.get('v2_email','').strip() or None,
                telefoon=f.get('v2_telefoon','').strip() or None,
                adres=f.get('v2_adres','').strip() or None,
                postcode=f.get('v2_postcode','').strip() or None,
                woonplaats=f.get('v2_woonplaats','').strip() or None,
                bsn_enc=None,
            ))
        db.zaak_bijwerken(zaak_id, f.get('soort'), f.get('omschrijving','').strip(),
                          f.get('status','actief'))
        flash('Dossier bijgewerkt.', 'ok')
        return redirect(url_for('dossier_detail', zaak_id=zaak_id))

    return render_template('dossier_form.html', soorten=db.ZAAK_SOORTEN,
                           statussen=db.ZAAK_STATUSSEN,
                           zaak=zaak, k1=k1, k2=k2, bewerken=True)


# ── Dossier verwijderen ───────────────────────────────────────────────────────

@app.route('/dossiers/<int:zaak_id>/verwijderen', methods=['POST'])
@login_required
def dossier_verwijderen(zaak_id):
    db.logboek_schrijven(zaak_id, 'Dossier verwijderd (definitief)')
    db.zaak_verwijderen(zaak_id)
    flash('Dossier en bijbehorende klantdata zijn definitief verwijderd (AVG).', 'ok')
    return redirect(url_for('dossiers'))


# ── Stukkenlijst ──────────────────────────────────────────────────────────────

@app.route('/stukken/<int:stuk_id>/status', methods=['POST'])
@login_required
def stuk_status(stuk_id):
    status  = request.form.get('status', 'ontbreekt')
    zaak_id = request.form.get('zaak_id', type=int)
    db.stuk_status_bijwerken(stuk_id, status)
    db.logboek_schrijven(zaak_id, f'Stukstatus gewijzigd naar "{status}"')
    return redirect(url_for('dossier_detail', zaak_id=zaak_id))


@app.route('/dossiers/<int:zaak_id>/stuk-toevoegen', methods=['POST'])
@login_required
def stuk_toevoegen(zaak_id):
    label = request.form.get('label','').strip()
    if label:
        db.stuk_toevoegen(zaak_id, label)
        db.logboek_schrijven(zaak_id, f'Stuk handmatig toegevoegd: {label}')
    return redirect(url_for('dossier_detail', zaak_id=zaak_id))


# ── Documentinname (Fase 2.2) ─────────────────────────────────────────────────

def _ollama_config():
    url   = db.instelling_ophalen('ollama_url',   default='http://localhost:11434')
    model = db.instelling_ophalen('ollama_model', default='qwen2.5:7b')
    return url, model


def _velden_lezen(doc) -> dict:
    """Ontsleutelt en parseert de opgeslagen velden van een document."""
    if not doc or not doc['velden_json']:
        return {}
    try:
        return json.loads(security.decrypt_field(doc['velden_json']))
    except Exception:
        return {}


def _velden_opslaan_dict(document_id: int, velden: dict, status: str = 'bevestigd'):
    enc = security.encrypt_field(json.dumps(velden, ensure_ascii=False))
    db.document_velden_opslaan(document_id, enc, status)


@app.route('/stukken/<int:stuk_id>/upload', methods=['POST'])
@login_required
def stuk_upload(stuk_id):
    stuk = db.stuk_ophalen(stuk_id)
    if not stuk:
        abort(404)
    zaak_id = stuk['zaak_id']
    bestand = request.files.get('bestand')
    if not bestand or not bestand.filename:
        flash('Geen bestand gekozen.', 'fout')
        return redirect(url_for('dossier_detail', zaak_id=zaak_id) + '#stukken')

    raw  = bestand.read()
    naam = bestand.filename
    mime = bestand.mimetype or 'application/octet-stream'

    # Versleuteld opslaan op schijf — dit is snel en blokkeert niet.
    pad_enc = security.save_encrypted_document(raw)
    doc_id = db.document_aanmaken(
        zaak_id, stuk_id, stuk['type'], naam, pad_enc,
        mime=mime, velden_json=None, ai_model=None, status='concept')
    # Stuk op 'ontvangen' tot de adviseur de gegevens bevestigt
    db.stuk_status_bijwerken(stuk_id, 'ontvangen')
    db.logboek_schrijven(zaak_id, f'Document geüpload: {naam}', f'Stuk: {stuk["label"]}')

    # Het uitlezen door de AI gebeurt op het controlescherm (niet-blokkerend).
    return redirect(url_for('document_controle', doc_id=doc_id))


@app.route('/documenten/<int:doc_id>/controle')
@login_required
def document_controle(doc_id):
    doc = db.document_ophalen(doc_id)
    if not doc:
        abort(404)
    stuk   = db.stuk_ophalen(doc['stuk_id']) if doc['stuk_id'] else None
    zaak   = db.zaak_ophalen(doc['zaak_id'])
    schema = intake.schema_voor(doc['type'])
    velden = _velden_lezen(doc)
    return render_template('document_controle.html',
                           doc=doc, stuk=stuk, zaak=zaak,
                           schema=schema, velden=velden,
                           stuk_type=doc['type'])


@app.route('/documenten/<int:doc_id>/opslaan', methods=['POST'])
@login_required
def document_opslaan(doc_id):
    doc = db.document_ophalen(doc_id)
    if not doc:
        abort(404)
    schema = intake.schema_voor(doc['type'])
    velden = {}
    for sleutel, _label, _hint in schema:
        velden[sleutel] = request.form.get(sleutel, '').strip()
    # extra handmatig toegevoegde notitie
    velden['_notitie'] = request.form.get('_notitie', '').strip()

    _velden_opslaan_dict(doc_id, velden, status='bevestigd')

    # Stuk koppelen en op 'gecontroleerd' zetten
    if doc['stuk_id']:
        db.stuk_document_koppelen(doc['stuk_id'], doc_id)
        db.stuk_status_bijwerken(doc['stuk_id'], 'gecontroleerd')
    db.logboek_schrijven(doc['zaak_id'], 'Documentgegevens bevestigd',
                         f'Type: {doc["type"]}')

    flash('Gegevens bevestigd en opgeslagen.', 'ok')
    return redirect(url_for('dossier_detail', zaak_id=doc['zaak_id']) + '#stukken')


@app.route('/documenten/<int:doc_id>/uitlezen', methods=['POST'])
@login_required
def document_uitlezen(doc_id):
    """Niet-blokkerend AI-uitlezen, aangeroepen vanaf het controlescherm via
    JavaScript. Geeft JSON terug zodat de pagina niet vastloopt."""
    doc = db.document_ophalen(doc_id)
    if not doc:
        return jsonify(ok=False, fout='Document niet gevonden.'), 404

    is_pdf = (doc['bestandsnaam'] or '').lower().endswith('.pdf') or \
             doc['mime'] == 'application/pdf'
    if not is_pdf:
        return jsonify(ok=False, fout='Automatisch uitlezen werkt alleen voor PDF. '
                       'Vul de gegevens handmatig in.')

    try:
        raw   = security.read_encrypted_document(doc['pad_enc'])
        tekst = intake.pdf_tekst(raw)
    except Exception as e:
        return jsonify(ok=False, fout=f'Kon de PDF niet uitlezen: {e}')

    if not intake.heeft_tekstlaag(tekst):
        return jsonify(ok=False, fout='Dit PDF lijkt een scan zonder tekstlaag. '
                       'Vul de gegevens handmatig in.')

    url, model = _ollama_config()
    if not intake.is_lokale_url(url):
        db.logboek_schrijven(None, 'AI-uitlezen geweigerd: niet-lokaal AI-adres',
                             f'ollama_url={url}')
        return jsonify(ok=False, fout='Het ingestelde AI-adres wijst niet naar deze '
                       'computer (localhost). Om te voorkomen dat klantgegevens het '
                       'apparaat verlaten is uitlezen geblokkeerd. Zet het AI-adres '
                       'in Instellingen terug naar http://localhost:11434.')
    if not intake.ollama_beschikbaar(url):
        return jsonify(ok=False, fout='De lokale AI (Ollama) draait niet. '
                       'Start de Ollama-app en probeer opnieuw, of vul handmatig in.')

    try:
        velden = intake.extraheer(doc['type'], tekst, model, url, timeout=660)
    except Exception as e:
        return jsonify(ok=False, fout=f'AI-uitlezen mislukt: {e}')

    _velden_opslaan_dict(doc_id, velden, status='concept')
    with db.get_db() as conn:
        conn.execute("UPDATE documenten SET ai_model=? WHERE id=?", (model, doc_id))
    return jsonify(ok=True, velden=velden, model=model)


@app.route('/documenten/<int:doc_id>/bestand')
@login_required
def document_bestand(doc_id):
    doc = db.document_ophalen(doc_id)
    if not doc:
        abort(404)
    try:
        raw = security.read_encrypted_document(doc['pad_enc'])
    except Exception:
        abort(404)
    return send_file(io.BytesIO(raw), mimetype=doc['mime'] or 'application/pdf',
                     download_name=doc['bestandsnaam'], as_attachment=False)


@app.route('/documenten/<int:doc_id>/verwijderen', methods=['POST'])
@login_required
def document_verwijderen(doc_id):
    doc = db.document_ophalen(doc_id)
    if not doc:
        abort(404)
    zaak_id = doc['zaak_id']
    stuk_id = doc['stuk_id']
    pad = db.document_verwijderen(doc_id)
    if pad and os.path.exists(pad):
        try:
            os.remove(pad)
        except OSError:
            pass
    if stuk_id:
        db.stuk_status_bijwerken(stuk_id, 'ontbreekt')
    db.logboek_schrijven(zaak_id, 'Document verwijderd', doc['bestandsnaam'])
    flash('Document verwijderd.', 'ok')
    return redirect(url_for('dossier_detail', zaak_id=zaak_id) + '#stukken')


# Opmerking: een UWV-verzekeringsbericht is NIET verplicht. De adviseur bepaalt
# zelf welke stukken worden aangeleverd; de salarisstrook is het vaste inkomensstuk.
# Wanneer er later wél een UWV-bericht in het dossier zit, kan in Fase 2.3 een
# numerieke vergelijking (loonstrook/werkgeversverklaring t.o.v. UWV) worden
# toegevoegd. Tot die tijd wordt er niet gewaarschuwd over een ontbrekend anker.


# ── Taken ─────────────────────────────────────────────────────────────────────

@app.route('/dossiers/<int:zaak_id>/taak-toevoegen', methods=['POST'])
@login_required
def taak_toevoegen(zaak_id):
    omschr  = request.form.get('omschrijving','').strip()
    deadline= request.form.get('deadline','').strip() or None
    if omschr:
        db.taak_toevoegen(zaak_id, omschr, deadline)
    return redirect(url_for('dossier_detail', zaak_id=zaak_id) + '#taken')


@app.route('/taken/<int:taak_id>/toggle', methods=['POST'])
@login_required
def taak_toggle(taak_id):
    zaak_id = request.form.get('zaak_id', type=int)
    db.taak_toggle(taak_id)
    return redirect(url_for('dossier_detail', zaak_id=zaak_id) + '#taken')


@app.route('/taken/<int:taak_id>/verwijderen', methods=['POST'])
@login_required
def taak_verwijderen(taak_id):
    zaak_id = request.form.get('zaak_id', type=int)
    db.taak_verwijderen(taak_id)
    return redirect(url_for('dossier_detail', zaak_id=zaak_id) + '#taken')


# ── Notities ──────────────────────────────────────────────────────────────────

@app.route('/dossiers/<int:zaak_id>/notitie', methods=['POST'])
@login_required
def notitie_toevoegen(zaak_id):
    tekst = request.form.get('tekst','').strip()
    if tekst:
        db.notitie_toevoegen(zaak_id, tekst)
        db.logboek_schrijven(zaak_id, 'Notitie toegevoegd')
    return redirect(url_for('dossier_detail', zaak_id=zaak_id) + '#notities')


@app.route('/notities/<int:notitie_id>/verwijderen', methods=['POST'])
@login_required
def notitie_verwijderen(notitie_id):
    zaak_id = request.form.get('zaak_id', type=int)
    db.notitie_verwijderen(notitie_id)
    return redirect(url_for('dossier_detail', zaak_id=zaak_id) + '#notities')


# ── Signaleringen ─────────────────────────────────────────────────────────────

@app.route('/signaleringen/<int:sig_id>/oplossen', methods=['POST'])
@login_required
def signalering_oplossen(sig_id):
    zaak_id = request.form.get('zaak_id', type=int)
    db.signalering_oplossen(sig_id)
    return redirect(url_for('dossier_detail', zaak_id=zaak_id))


# ── Export ────────────────────────────────────────────────────────────────────

@app.route('/export/dossier/<int:zaak_id>')
@login_required
def export_dossier(zaak_id):
    tmp = os.path.join(BASE_DIR, 'data', 'export_tmp')
    os.makedirs(tmp, exist_ok=True)
    pad = export.exporteer_dossier(zaak_id, tmp)
    db.logboek_schrijven(zaak_id, 'Dossier geëxporteerd naar Excel')
    return send_file(pad, as_attachment=True,
                     download_name=os.path.basename(pad))


@app.route('/export/alle')
@login_required
def export_alle():
    tmp = os.path.join(BASE_DIR, 'data', 'export_tmp')
    os.makedirs(tmp, exist_ok=True)
    pad = export.exporteer_alle_dossiers(tmp)
    db.logboek_schrijven(None, 'Alle dossiers geëxporteerd naar Excel')
    return send_file(pad, as_attachment=True,
                     download_name=os.path.basename(pad))


# ── Back-up ───────────────────────────────────────────────────────────────────

@app.route('/backup')
@login_required
def backup():
    backup_map = db.instelling_ophalen('backup_map', default='~/Desktop')
    backup_map = os.path.expanduser(backup_map)
    try:
        pad = security.create_backup(backup_map)
        db.logboek_schrijven(None, 'Back-up aangemaakt', pad)
        flash(f'Back-up opgeslagen: {pad}', 'ok')
    except Exception as e:
        flash(f'Back-up mislukt: {e}', 'fout')
    return redirect(url_for('instellingen'))


# ── Logboek ───────────────────────────────────────────────────────────────────

@app.route('/logboek')
@login_required
def logboek():
    zaak_id = request.args.get('zaak_id', type=int)
    regels  = db.logboek_ophalen(zaak_id)
    return render_template('logboek.html', regels=regels, zaak_id=zaak_id)


# ── Maximale hypotheek (Scherm 3, Fase 2.3) ──────────────────────────────────

def _normtabellen_met_instellingen(jaar: int) -> dict:
    """Laadt de normtabellen (JSON) en legt daar de via Instellingen
    opgeslagen waarden overheen, zodat jaarlijkse bedragen zonder
    codewijziging actueel te houden zijn."""
    nt = rekenkern.laad_normtabellen(jaar)
    cfg = {r['sleutel']: r['waarde'] for r in db.alle_instellingen_ophalen(jaar)}

    def _f(sleutel, standaard):
        try:
            return float(cfg[sleutel]) if cfg.get(sleutel) else standaard
        except ValueError:
            return standaard

    nt['toetsrente_minimum_kort'] = _f('toetsrente_minimum',
                                       nt['toetsrente_minimum_kort'])
    nhg = nt.setdefault('nhg', {})
    nhg['kostengrens']     = _f('nhg_grens',      nhg.get('kostengrens'))
    nhg['kostengrens_ebv'] = _f('nhg_grens_ebv',  nhg.get('kostengrens_ebv'))
    nhg['premie_pct']      = _f('nhg_premie_pct', nhg.get('premie_pct'))
    lb = nt['energielabel_bedragen']
    lb['E,F,G']  = _f('energielabel_EFG',           lb['E,F,G'])
    lb['C,D']    = _f('energielabel_CD',            lb['C,D'])
    lb['A,B']    = _f('energielabel_AB',            lb['A,B'])
    lb['A+,A++'] = _f('energielabel_Aplusplus',     lb['A+,A++'])
    lb['A+++']   = _f('energielabel_Aplusplusplus', lb['A+++'])
    lb['A++++']  = _f('energielabel_A4plus',        lb['A++++'])
    return nt


@app.route('/hypotheek', methods=['GET', 'POST'])
@login_required
def hypotheek():
    jaar = 2026
    resultaat = nhg = None
    form = request.form if request.method == 'POST' else {}
    if request.method == 'POST':
        try:
            nt = _normtabellen_met_instellingen(jaar)
            resultaat = rekenkern.bereken_maximale_hypotheek(
                bruto_jaarinkomen_1=float(form.get('inkomen1') or 0),
                bruto_jaarinkomen_2=float(form.get('inkomen2') or 0),
                rente_pct=float(form.get('rente') or 0),
                rentevast_10jr=(form.get('rentevast10') == 'ja'),
                woningwaarde=float(form.get('woningwaarde') or 0),
                energielabel=form.get('energielabel', 'C,D'),
                niet_aftrekbaar_deel_pct=float(form.get('niet_aftrekbaar') or 0),
                maandlasten_bkr=float(form.get('bkr') or 0),
                alimentatie_pm=float(form.get('alimentatie') or 0),
                studieschuld_oorspronkelijk=float(form.get('studieschuld') or 0),
                leenstelsel=form.get('leenstelsel', 'nieuw'),
                aow_binnen_10jr=(form.get('aow10') == 'ja'),
                pensioeninkomen_jaar=float(form.get('pensioen') or 0),
                normjaar=jaar, normtabellen=nt)
            nhg = rekenkern.nhg_toets(float(form.get('woningwaarde') or 0),
                                      False, normtabellen=nt)
            db.logboek_schrijven(None, 'Hypotheekberekening uitgevoerd')
        except (rekenkern.RekenkernFout, ValueError) as e:
            flash(str(e), 'fout')
    return render_template('hypotheek.html', form=form, resultaat=resultaat,
                           nhg=nhg, normjaar=jaar,
                           energielabels=rekenkern.ENERGIELABELS)


# ── Instellingen ──────────────────────────────────────────────────────────────

@app.route('/instellingen', methods=['GET', 'POST'])
@login_required
def instellingen():
    jaar = 2026
    if request.method == 'POST':
        f = request.form
        for sleutel in ['nhg_grens','nhg_grens_ebv','nhg_premie_pct',
                        'toetsrente_minimum',
                        'energielabel_EFG','energielabel_CD','energielabel_AB',
                        'energielabel_Aplusplus','energielabel_Aplusplusplus',
                        'energielabel_A4plus','backup_map','ollama_model']:
            val = f.get(sleutel,'').strip()
            if val:
                normjaar = None if sleutel in ('backup_map','ollama_model') else jaar
                db.instelling_opslaan(sleutel, val, normjaar)
        db.logboek_schrijven(None, 'Instellingen opgeslagen')
        flash('Instellingen opgeslagen.', 'ok')
        return redirect(url_for('instellingen'))

    cfg = {r['sleutel']: r['waarde'] for r in db.alle_instellingen_ophalen(jaar)}
    cfg.update({r['sleutel']: r['waarde'] for r in db.alle_instellingen_ophalen(None)})
    return render_template('instellingen.html', cfg=cfg, jaar=jaar)


# ── Wachtwoord wijzigen ───────────────────────────────────────────────────────

@app.route('/wachtwoord-wijzigen', methods=['GET', 'POST'])
@login_required
def wachtwoord_wijzigen():
    if request.method == 'POST':
        f      = request.form
        huidig = f.get('huidig','')
        nieuw  = f.get('nieuw','')
        nieuw2 = f.get('nieuw2','')
        if not security.unlock(huidig):
            flash('Huidig wachtwoord is onjuist.', 'fout')
        elif len(nieuw) < 8:
            flash('Nieuw wachtwoord moet minimaal 8 tekens zijn.', 'fout')
        elif nieuw != nieuw2:
            flash('Nieuwe wachtwoorden komen niet overeen.', 'fout')
        else:
            security.setup_password(nieuw)
            security.unlock(nieuw)
            db.logboek_schrijven(None, 'Wachtwoord gewijzigd')
            flash('Wachtwoord gewijzigd.', 'ok')
            return redirect(url_for('instellingen'))
    return render_template('wachtwoord_wijzigen.html')


# ── Template-hulpfuncties ─────────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    return dict(
        nu=datetime.now(),
        klant_naam=db.klant_volledige_naam,
        ZAAK_SOORTEN=db.ZAAK_SOORTEN,
        ZAAK_STATUSSEN=db.ZAAK_STATUSSEN,
        STUK_STATUSSEN=db.STUK_STATUSSEN,
    )


@app.template_filter('datum')
def datum_filter(s):
    if not s:
        return ''
    try:
        return datetime.fromisoformat(s).strftime('%d-%m-%Y')
    except Exception:
        return s


@app.template_filter('datum_tijd')
def datum_tijd_filter(s):
    if not s:
        return ''
    try:
        return datetime.fromisoformat(s).strftime('%d-%m-%Y %H:%M')
    except Exception:
        return s


# ── Start ─────────────────────────────────────────────────────────────────────

def _warmup_ai():
    """Laadt het AI-model alvast op de achtergrond zodat het eerste uitlezen snel is."""
    import time
    time.sleep(3)   # geef de server even tijd om te starten
    try:
        url, model = _ollama_config()
        if intake.is_lokale_url(url) and intake.ollama_beschikbaar(url):
            intake.warmup(model, url)
    except Exception:
        pass


if __name__ == '__main__':
    if not security.is_setup_done():
        db.init_db()   # maak tabellen alvast aan voor setup-redirect
    else:
        db.migreer()   # nieuwe tabellen/instellingen toevoegen aan bestaande database
        import threading
        threading.Thread(target=_warmup_ai, daemon=True).start()
    app.run(host='127.0.0.1', port=5757, debug=False)
