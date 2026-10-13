"""
documentintake.py — Fase 2.2: documenten uitlezen met lokale AI (Ollama)

Werkwijze:
  1. PDF-tekst wordt lokaal uitgelezen (PyMuPDF).
  2. Per documenttype is een veldschema gedefinieerd (HDN-verwant).
  3. De tekst + het schema gaan naar een lokaal AI-model via Ollama.
  4. Het model geeft JSON terug; die wordt op de schemavelden gelegd.

Alles gebeurt op de eigen Mac; er gaat niets naar internet.
Het UWV-verzekeringsbericht is het betrouwbaarheidsanker; loonstrook en
werkgeversverklaring worden daar later (Fase 2.3) tegenaan gevalideerd.
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error


# ── Veldschema's per documenttype ────────────────────────────────────────────
# Elk veld: (sleutel, label, hint-voor-de-AI)

_GENERIEK = [
    ('omschrijving',          'Soort document',          'Wat voor document is dit?'),
    ('belangrijkste_gegevens','Belangrijkste gegevens',  'Korte samenvatting van de relevante gegevens.'),
]

VELD_SCHEMAS: dict[str, list[tuple[str, str, str]]] = {

    # ── ANKER: UWV-verzekeringsbericht ──
    'uwv_bericht': [
        ('werknemer_naam',       'Naam werknemer',              'Volledige naam van de verzekerde/werknemer.'),
        ('peildatum',            'Datum bericht',               'Datum waarop het bericht is opgesteld (dd-mm-jjjj).'),
        ('huidige_werkgever',    'Huidige werkgever',           'Naam van de meest recente werkgever.'),
        ('soort_dienstverband',  'Soort dienstverband',         'Vast, tijdelijk/bepaalde tijd, of onbekend.'),
        ('datum_in_dienst',      'In dienst sinds',             'Begindatum dienstverband huidige werkgever (dd-mm-jjjj).'),
        ('sv_loon_maand',        'SV-loon laatste maand (€)',   'Sociaalverzekeringsloon van de laatst vermelde maand, alleen het bedrag.'),
        ('sv_loon_jaar',         'SV-loon op jaarbasis (€)',    'Jaarbedrag SV-loon indien vermeld, anders leeg.'),
        ('aantal_dienstverbanden','Aantal dienstverbanden',     'Hoeveel verschillende dienstverbanden/werkgevers staan vermeld?'),
        ('samenvatting',         'Samenvatting dienstverbanden','Korte opsomming per werkgever: periode en loon.'),
    ],

    'loonstrook': [
        ('werknemer_naam',       'Naam werknemer',              "Volledige naam van de werknemer. Staat meestal bij de geadresseerde ('Aan:' / 'T.a.v.'), niet bij het label 'Werknemer' (dat is vaak een nummer). Negeer watermerken zoals 'SALARISAFREKENING'."),
        ('werkgever',            'Werkgever',                   'Naam werkgever.'),
        ('periode',              'Periode',                     'Loonperiode (bv. maand/jaar).'),
        ('bruto_maandsalaris',   'Bruto maandsalaris (€)',      'Bruto salaris deze periode, alleen het bedrag.'),
        ('vakantiegeld',         'Vakantiegeld',                'Percentage of bedrag vakantiegeld indien vermeld.'),
        ('onregelmatigheidstoeslag','Onregelmatigheidstoeslag (€)','Bedrag ORT/toeslag indien vermeld.'),
        ('netto_uitbetaald',     'Netto uitbetaald (€)',        'Netto uitbetaald bedrag.'),
        ('bijzondere_beloningen','Bijzondere beloningen',       'Bonus, 13e maand, eindejaarsuitkering e.d.'),
    ],

    'werkgeversverklaring': [
        ('werknemer_naam',       'Naam werknemer',              'Volledige naam.'),
        ('werkgever',            'Werkgever',                   'Naam werkgever.'),
        ('functie',              'Functie',                     'Functietitel.'),
        ('soort_dienstverband',  'Soort dienstverband',         'Vast (onbepaalde tijd) of bepaalde tijd.'),
        ('datum_in_dienst',      'In dienst sinds',             'Begindatum (dd-mm-jjjj).'),
        ('intentieverklaring',   'Intentieverklaring',          'Is er een verklaring voortzetting dienstverband? Ja/Nee/N.v.t.'),
        ('bruto_jaarsalaris',    'Bruto jaarsalaris (€)',       'Overeengekomen bruto jaarsalaris, alleen het bedrag.'),
        ('vakantiegeld',         'Vakantiegeld (€)',            'Bedrag vakantiegeld per jaar.'),
        ('dertiende_maand',      '13e maand (€)',               'Bedrag 13e maand indien van toepassing.'),
        ('onregelmatigheidstoeslag','Onregelmatigheidstoeslag (€)','Structurele toeslag indien vermeld.'),
        ('eindejaarsuitkering',  'Eindejaarsuitkering (€)',     'Bedrag indien vermeld.'),
    ],

    'jaaropgave': [
        ('werknemer_naam',       'Naam werknemer',              'Volledige naam.'),
        ('werkgever',            'Werkgever',                   'Naam werkgever.'),
        ('jaar',                 'Jaar',                        'Kalenderjaar van de opgave.'),
        ('fiscaal_loon',         'Fiscaal loon / loon LH (€)',  'Loon voor de loonheffing, alleen het bedrag.'),
        ('ingehouden_loonheffing','Ingehouden loonheffing (€)', 'Bedrag ingehouden loonheffing.'),
        ('arbeidskorting',       'Verrekende arbeidskorting (€)','Bedrag arbeidskorting indien vermeld.'),
    ],

    'pensioen': [
        ('naam',                 'Naam',                        'Naam van de deelnemer.'),
        ('pensioenuitvoerder',   'Pensioenuitvoerder',          'Naam pensioenfonds/verzekeraar.'),
        ('ouderdomspensioen',    'Te bereiken ouderdomspensioen (€)','Bruto jaarbedrag indien vermeld.'),
        ('partnerpensioen',      'Partnerpensioen (€)',         'Bruto jaarbedrag partnerpensioen.'),
        ('aow_leeftijd',         'AOW-leeftijd',                'Verwachte AOW-leeftijd indien vermeld.'),
        ('peildatum',            'Peildatum',                   'Datum van het overzicht (dd-mm-jjjj).'),
    ],

    'bankafschrift': [
        ('rekeninghouder',       'Rekeninghouder',              'Naam op de rekening.'),
        ('iban',                 'IBAN',                        'Rekeningnummer (IBAN).'),
        ('periode',              'Periode',                     'Periode van het afschrift.'),
        ('salaris_bijschrijving','Terugkerende salarisbijschrijving (€)','Maandelijks bijgeschreven salaris indien herkenbaar.'),
        ('vaste_lasten',         'Opvallende vaste lasten',     'Huur, hypotheek, alimentatie, leningen e.d. die opvallen.'),
    ],

    'koopovereenkomst': [
        ('adres_woning',         'Adres woning',                'Volledig adres van de woning.'),
        ('koopsom',              'Koopsom (€)',                 'Koopsom, alleen het bedrag.'),
        ('kosten_koper',         'k.k. of v.o.n.',              'Kosten koper of vrij op naam.'),
        ('datum_ondertekening',  'Datum ondertekening',         'Datum (dd-mm-jjjj).'),
        ('ontbindende_voorwaarde_financiering','Financieringsvoorbehoud tot','Datum ontbindende voorwaarde financiering.'),
        ('verkoper',             'Verkoper',                    'Naam verkoper.'),
        ('koper',                'Koper',                       'Naam koper(s).'),
    ],

    'taxatierapport': [
        ('adres_woning',         'Adres woning',                'Volledig adres.'),
        ('marktwaarde',          'Marktwaarde (€)',             'Getaxeerde marktwaarde, alleen het bedrag.'),
        ('marktwaarde_na_verbouwing','Marktwaarde na verbouwing (€)','Indien van toepassing.'),
        ('taxatiedatum',         'Taxatiedatum',                'Datum (dd-mm-jjjj).'),
        ('taxateur',             'Taxateur',                    'Naam taxateur/bureau.'),
        ('nwwi_gevalideerd',     'NWWI-gevalideerd',            'Is het rapport NWWI-gevalideerd? Ja/Nee.'),
    ],

    'legitimatie': [
        ('naam',                 'Naam',                        'Volledige naam.'),
        ('documentsoort',        'Soort document',              'Paspoort, identiteitskaart of rijbewijs.'),
        ('documentnummer',       'Documentnummer',              'Nummer van het document.'),
        ('geldig_tot',           'Geldig tot',                  'Vervaldatum (dd-mm-jjjj).'),
        ('nationaliteit',        'Nationaliteit',               'Nationaliteit indien vermeld.'),
    ],
}


def schema_voor(dtype: str) -> list[tuple[str, str, str]]:
    return VELD_SCHEMAS.get(dtype, _GENERIEK)


# ── PDF-tekst uitlezen ───────────────────────────────────────────────────────

def pdf_tekst(raw: bytes) -> str:
    """Leest de tekstlaag uit een PDF (lokaal, met PyMuPDF).
    Geeft lege string terug als er geen tekstlaag is (waarschijnlijk een scan)."""
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise RuntimeError(
            "PyMuPDF ontbreekt. Voer 'Installeer FinanZen.command' opnieuw uit."
        ) from e
    delen = []
    with fitz.open(stream=raw, filetype='pdf') as doc:
        for pagina in doc:
            delen.append(pagina.get_text("text"))
    return "\n".join(delen).strip()


def heeft_tekstlaag(tekst: str) -> bool:
    return len(tekst.strip()) >= 40


# ── Ollama ───────────────────────────────────────────────────────────────────

def ollama_beschikbaar(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip('/') + '/api/tags', timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def warmup(model: str, url: str, timeout: float = 600.0) -> bool:
    """Laadt het model alvast in het geheugen (en houdt het daar) zodat het
    eerste echte uitlezen snel gaat. Best-effort: fouten worden genegeerd."""
    payload = {"model": model, "prompt": "", "stream": False, "keep_alive": "1h"}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url.rstrip('/') + '/api/generate', data=data,
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
        return True
    except Exception:
        return False


def beschikbare_modellen(url: str, timeout: float = 3.0) -> list[str]:
    try:
        with urllib.request.urlopen(url.rstrip('/') + '/api/tags', timeout=timeout) as r:
            data = json.loads(r.read().decode())
        return [m.get('name', '') for m in data.get('models', [])]
    except Exception:
        return []


def _bouw_prompt(dtype: str, tekst: str) -> tuple[str, str]:
    schema = schema_voor(dtype)
    velden_omschrijving = "\n".join(
        f'- "{sleutel}": {hint}' for sleutel, _label, hint in schema)
    sleutels = [s for s, _l, _h in schema]
    systeem = (
        "Je bent een nauwkeurige assistent voor een Nederlandse hypotheekadviseur. "
        "Je haalt gegevens uit financiële documenten en geeft uitsluitend geldige JSON terug. "
        "Verzin NOOIT gegevens: staat iets niet letterlijk in de tekst, gebruik dan een lege string. "
        "Bedragen geef je als getal met punt of komma zoals in het document, zonder valutateken. "
        "Voor de naam van de persoon: kijk naar de geadresseerde ('Aan:', 'T.a.v.', 'De heer/Mevrouw') "
        "en negeer logo's, watermerken, bedrijfsnamen van de afzender en kolomlabels."
    )
    gebruiker = (
        f"Hieronder staat de uitgelezen tekst van een document van het type '{dtype}'.\n"
        f"Haal de volgende velden eruit en geef ALLEEN een JSON-object terug met precies "
        f"deze sleutels: {sleutels}.\n\n"
        f"Toelichting per veld:\n{velden_omschrijving}\n\n"
        f"=== DOCUMENTTEKST ===\n{tekst[:7000]}\n=== EINDE TEKST ==="
    )
    return systeem, gebruiker


def extraheer(dtype: str, tekst: str, model: str, url: str,
              timeout: float = 120.0) -> dict:
    """Stuurt de documenttekst naar Ollama en geeft een dict {sleutel: waarde}
    terug op basis van het veldschema. Sleutels die het model niet vult,
    worden lege strings."""
    systeem, gebruiker = _bouw_prompt(dtype, tekst)
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "keep_alive": "1h",          # houd het model na laden in het geheugen
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": systeem},
            {"role": "user",   "content": gebruiker},
        ],
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url.rstrip('/') + '/api/chat', data=data,
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            antwoord = json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise RuntimeError(
            f"Geen (tijdig) antwoord van de lokale AI (Ollama): {e}") from e

    inhoud = (antwoord.get('message') or {}).get('content', '') or ''
    ruw = _parse_json(inhoud)

    # Normaliseer naar de schemavelden
    resultaat = {}
    for sleutel, _label, _hint in schema_voor(dtype):
        waarde = ruw.get(sleutel, '')
        if waarde is None:
            waarde = ''
        resultaat[sleutel] = str(waarde).strip()
    return resultaat


def _parse_json(tekst: str) -> dict:
    """Robuust JSON uit een modelantwoord halen."""
    tekst = tekst.strip()
    try:
        return json.loads(tekst)
    except Exception:
        pass
    # Probeer het eerste {...}-blok eruit te knippen
    start = tekst.find('{')
    eind  = tekst.rfind('}')
    if start != -1 and eind != -1 and eind > start:
        try:
            return json.loads(tekst[start:eind + 1])
        except Exception:
            pass
    return {}


# ── Privacy-waarborg: AI-verkeer mag de computer niet verlaten ───────────────

def is_lokale_url(url: str) -> bool:
    """True als de AI-URL naar deze computer zelf wijst (loopback).

    Alle documenttekst gaat naar dit adres; alles wat niet lokaal is zou
    klantgegevens het apparaat uit sturen en is daarom niet toegestaan.
    """
    from urllib.parse import urlparse
    try:
        host = (urlparse(url).hostname or '').lower()
    except Exception:
        return False
    return host in ('localhost', '127.0.0.1', '::1') or host.startswith('127.')
