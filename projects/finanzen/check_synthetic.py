"""Synthetic local audit. Uses source unchanged; never opens the real data store."""
import io, json, sys, tempfile, unittest, subprocess
from pathlib import Path
from datetime import datetime, timedelta
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'source'))
import security, database as db, documentintake as intake, rekenkern
from unittest.mock import patch

with tempfile.TemporaryDirectory() as tmp:
    security.DATA_DIR = tmp
    security.CFG_PATH = str(Path(tmp) / 'config.json')
    security.DOCS_DIR = str(Path(tmp) / 'documents')
    db.DB_PATH = str(Path(tmp) / 'synthetic.db')
    security.setup_password('synthetic-audit-only')
    assert security.unlock('synthetic-audit-only')
    db.init_db(); db.migreer()
    import app as module
    client = module.app.test_client()
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['last_activity'] = datetime.now().isoformat()
    customer = dict(voornaam='Synthetic', tussenvoegsel='', achternaam='Example', geboortedatum='', email='example@example.invalid', telefoon='', adres='', postcode='', woonplaats='', bsn_enc='')
    kid = db.klant_aanmaken(customer)
    zid = db.zaak_aanmaken(kid, None, 'aankoop', 'Synthetic audit')
    sid = db.stuk_toevoegen(zid, 'Synthetic PDF', 'loonstrook')
    data = b'%PDF synthetic fixture'
    upload = client.post(f'/stukken/{sid}/upload', data={'bestand': (io.BytesIO(data), 'synthetic.pdf')}, content_type='multipart/form-data')
    assert upload.status_code == 302
    doc = db.document_van_stuk(sid); did = doc['id']
    assert doc['status'] == 'concept'
    assert db.stuk_ophalen(sid)['status'] == 'ontvangen'
    assert Path(doc['pad_enc']).read_bytes() != data
    assert security.read_encrypted_document(doc['pad_enc']) == data
    with patch.object(intake, 'pdf_tekst', return_value='Synthetic document text ' * 30), patch.object(intake, 'heeft_tekstlaag', return_value=True), patch.object(intake, 'ollama_beschikbaar', return_value=True) as available, patch.object(intake, 'extraheer', return_value={'werknemer_naam': 'Synthetic Example'}) as extract:
        db.instelling_opslaan('ollama_url', 'https://example.invalid')
        assert client.post(f'/documenten/{did}/uitlezen').json['ok'] is False
        available.assert_not_called(); extract.assert_not_called()
        db.instelling_opslaan('ollama_url', 'http://localhost:11434')
        assert client.post(f'/documenten/{did}/uitlezen').json['ok'] is True
        assert db.document_ophalen(did)['status'] == 'concept'
        assert module._velden_lezen(db.document_ophalen(did))['werknemer_naam'] == 'Synthetic Example'
    saved = client.post(f'/documenten/{did}/opslaan', data={'werknemer_naam': 'Human corrected example', '_notitie': 'Synthetic confirmation'})
    assert saved.status_code == 302
    assert db.document_ophalen(did)['status'] == 'bevestigd'
    assert db.stuk_ophalen(sid)['status'] == 'gecontroleerd'
    assert module._velden_lezen(db.document_ophalen(did))['werknemer_naam'] == 'Human corrected example'
    assert client.get(f'/documenten/{did}/bestand').data == data
    assert any(row['actie'] == 'Documentgegevens bevestigd' for row in db.logboek_ophalen(zid))
    task = db.taak_toevoegen(zid, 'Synthetic task')
    assert db.taak_toggle(task) != db.taak_toggle(task)
    with client.session_transaction() as session:
        session['last_activity'] = (datetime.now() - timedelta(minutes=16)).isoformat()
    assert client.get('/dossiers').status_code == 302
    assert not security.is_unlocked()
    print('PASS: isolated CRM, encrypted file round trip, remote AI refusal, mocked local extraction, concept to human confirmation, checklist, audit, tasks and inactivity lock')
    print('Limit: AI responses mocked; no real inference, customer data or security/compliance certification.')

cases = json.loads((ROOT / 'portaal/parity_cases.json').read_text())
nt = rekenkern.laad_normtabellen(2026)
mapping = {'rentevast_10jr':'rentevast10jr','aow_binnen_10jr':'aowBinnen10jr'}
def camel(key):
    parts = key.split('_')
    return mapping.get(key, parts[0] + ''.join(p[:1].upper()+p[1:] for p in parts[1:]))
requests = [{'invoer':{camel(k):v for k,v in c['invoer'].items()}, 'nt':nt} for c in cases]
js = "const fs=require('node:fs'); const core=require(process.argv[1]);const rows=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(rows.map(r=>core.berekenMaximaleHypotheek(r.invoer,r.nt))));"
result = subprocess.run([__import__('os').environ.get('NODE_BIN', 'node'),'-e',js,str(ROOT/'portaal/rekenkern.js')], input=json.dumps(requests), text=True, capture_output=True, check=True)
results = json.loads(result.stdout)
for case, actual in zip(cases, results):
    expected = rekenkern.bereken_maximale_hypotheek(**case['invoer'], normtabellen=nt)
    assert abs(actual['uitkomst']['maximale_hypotheek'] - expected['uitkomst']['maximale_hypotheek']) <= .01
    assert actual['uitkomst']['begrenzing'] == expected['uitkomst']['begrenzing']
    assert actual['tussenstappen']['rentebandindex'] == expected['tussenstappen']['rentebandindex']
print(f'PASS: {len(cases)} current Python versus JavaScript calculation scenarios within one cent with matching limit and band')
print('Limit: consistency of archived model inputs, not current mortgage advice or legal validation.')
