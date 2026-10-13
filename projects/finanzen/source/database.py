"""
database.py — SQLite-schema en alle CRUD-functies
"""
from __future__ import annotations
import sqlite3, os, json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, 'data', 'finanzen.db')

ZAAK_SOORTEN = {
    'aankoop_bestaand':  'Aankoop bestaande woning',
    'aankoop_nieuwbouw': 'Aankoop nieuwbouw',
    'oversluiten':       'Oversluiten',
    'verhoging':         'Verhoging / heropname',
    'anders':            'Anders',
}

ZAAK_STATUSSEN = {
    'actief':    'Actief',
    'afgerond':  'Afgerond',
    'vervallen': 'Vervallen',
}

# ── Stukkenlijst-sjablonen per zaaktype ─────────────────────────────────────
# (label, type, aanvrager 1=klant-specifiek 0=zaak-specifiek, verplicht)
_STUKKEN_BASE = [
    ('Salarisstrook — aanvrager {n}',              'loonstrook',          1, True),
    ('UWV-verzekeringsbericht — aanvrager {n}',    'uwv_bericht',         1, True),
    ('Werkgeversverklaring — aanvrager {n}',       'werkgeversverklaring',1, True),
    ('Jaaropgave — aanvrager {n}',                 'jaaropgave',          1, True),
    ('Legitimatiebewijs — aanvrager {n}',          'legitimatie',         1, True),
    ('Pensioenoverzicht — aanvrager {n}',          'pensioen',            1, False),
    ('Bankafschriften (3 maanden) — aanvrager {n}','bankafschrift',       1, True),
]

STUKKEN_TEMPLATES = {
    'aankoop_bestaand': _STUKKEN_BASE + [
        ('Koopovereenkomst',                       'koopovereenkomst',    0, True),
        ('Taxatierapport (NWWI)',                  'taxatierapport',      0, True),
    ],
    'aankoop_nieuwbouw': _STUKKEN_BASE + [
        ('Koop-/aannemersovereenkomst',            'koopovereenkomst',    0, True),
        ('Bouwtekening / specificaties',           'bouwtekening',        0, False),
    ],
    'oversluiten': _STUKKEN_BASE + [
        ('Hypotheekakte huidige lening',           'hypotheekakte',       0, True),
        ('Taxatierapport (NWWI)',                  'taxatierapport',      0, False),
    ],
    'verhoging': _STUKKEN_BASE + [
        ('Taxatierapport (NWWI)',                  'taxatierapport',      0, True),
    ],
    'anders': [
        ('Legitimatiebewijs — aanvrager 1',        'legitimatie',         1, True),
        ('Bankafschriften (3 maanden)',             'bankafschrift',       0, True),
    ],
}

STUK_STATUSSEN = {
    'ontbreekt':          ('Ontbreekt',     'status-ontbreekt'),
    'ontvangen':          ('Ontvangen',     'status-ontvangen'),
    'gecontroleerd':      ('Gecontroleerd', 'status-ok'),
    'niet_van_toepassing':('N.v.t.',        'status-nvt'),
}

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS klanten (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    voornaam        TEXT NOT NULL,
    tussenvoegsel   TEXT,
    achternaam      TEXT NOT NULL,
    geboortedatum   TEXT,
    email           TEXT,
    telefoon        TEXT,
    adres           TEXT,
    postcode        TEXT,
    woonplaats      TEXT,
    bsn_enc         TEXT,
    created_at      TEXT DEFAULT (datetime('now','localtime')),
    updated_at      TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS zaken (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    aanvrager1_id   INTEGER NOT NULL REFERENCES klanten(id),
    aanvrager2_id   INTEGER REFERENCES klanten(id),
    soort           TEXT NOT NULL DEFAULT 'aankoop_bestaand',
    omschrijving    TEXT,
    status          TEXT NOT NULL DEFAULT 'actief',
    created_at      TEXT DEFAULT (datetime('now','localtime')),
    updated_at      TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS stukken (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    zaak_id     INTEGER NOT NULL REFERENCES zaken(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    type        TEXT NOT NULL,
    aanvrager   INTEGER DEFAULT 0,
    verplicht   INTEGER DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'ontbreekt',
    document_id INTEGER,
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS taken (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    zaak_id     INTEGER NOT NULL REFERENCES zaken(id) ON DELETE CASCADE,
    omschrijving TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    deadline    TEXT,
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS notities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    zaak_id     INTEGER NOT NULL REFERENCES zaken(id) ON DELETE CASCADE,
    tekst       TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS signaleringen (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    zaak_id     INTEGER NOT NULL REFERENCES zaken(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,
    bericht     TEXT NOT NULL,
    ernst       TEXT NOT NULL DEFAULT 'info',
    opgelost    INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS logboek (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    zaak_id     INTEGER,
    actie       TEXT NOT NULL,
    details     TEXT,
    timestamp   TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS instellingen (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sleutel     TEXT NOT NULL,
    waarde      TEXT NOT NULL,
    normjaar    INTEGER,
    UNIQUE(sleutel, normjaar)
);

CREATE TABLE IF NOT EXISTS documenten (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    zaak_id       INTEGER NOT NULL REFERENCES zaken(id) ON DELETE CASCADE,
    stuk_id       INTEGER REFERENCES stukken(id) ON DELETE SET NULL,
    type          TEXT NOT NULL,
    bestandsnaam  TEXT NOT NULL,
    pad_enc       TEXT NOT NULL,
    mime          TEXT,
    velden_json   TEXT,
    ai_model      TEXT,
    status        TEXT NOT NULL DEFAULT 'concept',
    created_at    TEXT DEFAULT (datetime('now','localtime')),
    updated_at    TEXT DEFAULT (datetime('now','localtime'))
);
"""

DEFAULT_INSTELLINGEN = [
    ('nhg_grens',            '470000',   2026),
    ('nhg_grens_ebv',        '498200',   2026),
    ('nhg_premie_pct',       '0.4',      2026),
    ('toetsrente_minimum',   '5.0',      2026),
    ('energielabel_EFG',     '0',        2026),
    ('energielabel_CD',      '5000',     2026),
    ('energielabel_AB',      '10000',    2026),
    ('energielabel_Aplusplus','20000',   2026),
    ('energielabel_Aplusplusplus','25000',2026),
    ('energielabel_A4plus',  '30000',    2026),
    ('actief_normjaar',      '2026',     None),
    ('backup_map',           '~/Desktop',None),
    ('ollama_model',         'qwen2.5:7b', None),
    ('ollama_url',           'http://localhost:11434', None),
]


# ── DB-verbinding ────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        conn.executescript(SCHEMA)
    _seed_instellingen()


def _seed_instellingen():
    with get_db() as conn:
        for sleutel, waarde, jaar in DEFAULT_INSTELLINGEN:
            if jaar is None:
                # NULL geldt in SQLite als uniek, dus INSERT OR IGNORE voorkomt
                # geen duplicaten — handmatig op bestaan controleren.
                bestaat = conn.execute(
                    "SELECT 1 FROM instellingen WHERE sleutel=? AND normjaar IS NULL",
                    (sleutel,)).fetchone()
                if not bestaat:
                    conn.execute(
                        "INSERT INTO instellingen (sleutel, waarde, normjaar) VALUES (?,?,NULL)",
                        (sleutel, waarde))
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO instellingen (sleutel, waarde, normjaar) VALUES (?,?,?)",
                    (sleutel, waarde, jaar))


def migreer():
    """Voert het schema veilig opnieuw uit zodat nieuwe tabellen/instellingen
    ook in bestaande databases verschijnen. Alles is IF NOT EXISTS / OR IGNORE,
    dus dit is veilig om bij elke start aan te roepen."""
    if not os.path.exists(DB_PATH):
        return
    with get_db() as conn:
        conn.executescript(SCHEMA)
        # Ruim eventueel eerder ontstane dubbele NULL-normjaar-rijen op (één per sleutel).
        conn.execute("""
            DELETE FROM instellingen
            WHERE normjaar IS NULL AND id NOT IN (
                SELECT MIN(id) FROM instellingen WHERE normjaar IS NULL GROUP BY sleutel
            )
        """)
    _seed_instellingen()


# ── Hulpfuncties ─────────────────────────────────────────────────────────────

def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _row(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def _rows(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


# ── Klanten ──────────────────────────────────────────────────────────────────

def klant_aanmaken(data: dict) -> int:
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO klanten (voornaam,tussenvoegsel,achternaam,geboortedatum,
                email,telefoon,adres,postcode,woonplaats,bsn_enc)
            VALUES (:voornaam,:tussenvoegsel,:achternaam,:geboortedatum,
                :email,:telefoon,:adres,:postcode,:woonplaats,:bsn_enc)
        """, data)
        return cur.lastrowid


def klant_bijwerken(klant_id: int, data: dict) -> None:
    data['id'] = klant_id
    data['updated_at'] = _now()
    with get_db() as conn:
        conn.execute("""
            UPDATE klanten SET voornaam=:voornaam, tussenvoegsel=:tussenvoegsel,
                achternaam=:achternaam, geboortedatum=:geboortedatum, email=:email,
                telefoon=:telefoon, adres=:adres, postcode=:postcode,
                woonplaats=:woonplaats, bsn_enc=:bsn_enc, updated_at=:updated_at
            WHERE id=:id
        """, data)


def klant_ophalen(klant_id: int):
    with get_db() as conn:
        return _row(conn, "SELECT * FROM klanten WHERE id=?", (klant_id,))


def klant_volledige_naam(k) -> str:
    if not k:
        return ''
    delen = [k['voornaam']]
    if k['tussenvoegsel']:
        delen.append(k['tussenvoegsel'])
    delen.append(k['achternaam'])
    return ' '.join(delen)


# ── Zaken ────────────────────────────────────────────────────────────────────

def zaak_aanmaken(aanvrager1_id: int, aanvrager2_id: int | None,
                  soort: str, omschrijving: str) -> int:
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO zaken (aanvrager1_id, aanvrager2_id, soort, omschrijving)
            VALUES (?,?,?,?)
        """, (aanvrager1_id, aanvrager2_id, soort, omschrijving))
        zaak_id = cur.lastrowid
    _maak_stukkenlijst(zaak_id, soort, aanvrager2_id is not None)
    logboek_schrijven(zaak_id, 'Dossier aangemaakt',
                      f'Soort: {ZAAK_SOORTEN.get(soort, soort)}')
    return zaak_id


def zaak_bijwerken(zaak_id: int, soort: str, omschrijving: str, status: str) -> None:
    with get_db() as conn:
        conn.execute("""
            UPDATE zaken SET soort=?, omschrijving=?, status=?, updated_at=?
            WHERE id=?
        """, (soort, omschrijving, status, _now(), zaak_id))
    logboek_schrijven(zaak_id, 'Dossier bijgewerkt')


def zaak_verwijderen(zaak_id: int) -> None:
    with get_db() as conn:
        zaak = _row(conn, "SELECT aanvrager1_id, aanvrager2_id FROM zaken WHERE id=?", (zaak_id,))
        conn.execute("DELETE FROM zaken WHERE id=?", (zaak_id,))
        # Verwijder klanten als ze niet aan andere zaken gekoppeld zijn
        for kid in [zaak['aanvrager1_id'], zaak['aanvrager2_id']]:
            if kid:
                cnt = conn.execute(
                    "SELECT COUNT(*) FROM zaken WHERE aanvrager1_id=? OR aanvrager2_id=?",
                    (kid, kid)).fetchone()[0]
                if cnt == 0:
                    conn.execute("DELETE FROM klanten WHERE id=?", (kid,))


def zaak_ophalen(zaak_id: int):
    with get_db() as conn:
        return _row(conn, "SELECT * FROM zaken WHERE id=?", (zaak_id,))


def alle_zaken_ophalen():
    """Alle zaken met naam aanvrager(s) — voor het dossieroverzicht."""
    sql = """
        SELECT z.*, k1.voornaam||COALESCE(' '||k1.tussenvoegsel,'')||' '||k1.achternaam AS naam1,
               CASE WHEN k2.id IS NOT NULL
                    THEN k2.voornaam||COALESCE(' '||k2.tussenvoegsel,'')||' '||k2.achternaam
                    ELSE NULL END AS naam2,
               (SELECT COUNT(*) FROM stukken WHERE zaak_id=z.id AND status='ontbreekt' AND verplicht=1) AS ontbrekend
        FROM zaken z
        JOIN klanten k1 ON k1.id = z.aanvrager1_id
        LEFT JOIN klanten k2 ON k2.id = z.aanvrager2_id
        ORDER BY z.updated_at DESC
    """
    with get_db() as conn:
        return _rows(conn, sql)


# ── Stukkenlijst ─────────────────────────────────────────────────────────────

def _maak_stukkenlijst(zaak_id: int, soort: str, heeft_partner: bool) -> None:
    template = STUKKEN_TEMPLATES.get(soort, STUKKEN_TEMPLATES['anders'])
    stukken  = []
    for label, stype, aanvrager, verplicht in template:
        if aanvrager == 1:
            stukken.append((zaak_id, label.format(n=1), stype, 1, int(verplicht)))
            if heeft_partner:
                stukken.append((zaak_id, label.format(n=2), stype, 2, int(verplicht)))
        else:
            stukken.append((zaak_id, label, stype, 0, int(verplicht)))
    with get_db() as conn:
        conn.executemany(
            "INSERT INTO stukken (zaak_id,label,type,aanvrager,verplicht) VALUES (?,?,?,?,?)",
            stukken)


def stukken_ophalen(zaak_id: int):
    with get_db() as conn:
        return _rows(conn, "SELECT * FROM stukken WHERE zaak_id=? ORDER BY aanvrager,id", (zaak_id,))


def stuk_status_bijwerken(stuk_id: int, status: str) -> None:
    with get_db() as conn:
        conn.execute("UPDATE stukken SET status=?, updated_at=? WHERE id=?",
                     (status, _now(), stuk_id))


def stuk_toevoegen(zaak_id: int, label: str, stype: str = 'overig',
                   verplicht: bool = False) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO stukken (zaak_id,label,type,verplicht) VALUES (?,?,?,?)",
            (zaak_id, label, stype, int(verplicht)))
        return cur.lastrowid


def stuk_ophalen(stuk_id: int):
    with get_db() as conn:
        return _row(conn, "SELECT * FROM stukken WHERE id=?", (stuk_id,))


def stuk_document_koppelen(stuk_id: int, document_id: int) -> None:
    with get_db() as conn:
        conn.execute("UPDATE stukken SET document_id=?, updated_at=? WHERE id=?",
                     (document_id, _now(), stuk_id))


# ── Documenten (Fase 2.2 — documentinname) ───────────────────────────────────

def document_aanmaken(zaak_id: int, stuk_id, dtype: str, bestandsnaam: str,
                      pad_enc: str, mime: str = None, velden_json: str = None,
                      ai_model: str = None, status: str = 'concept') -> int:
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO documenten (zaak_id,stuk_id,type,bestandsnaam,pad_enc,
                mime,velden_json,ai_model,status)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (zaak_id, stuk_id, dtype, bestandsnaam, pad_enc,
              mime, velden_json, ai_model, status))
        return cur.lastrowid


def document_ophalen(document_id: int):
    with get_db() as conn:
        return _row(conn, "SELECT * FROM documenten WHERE id=?", (document_id,))


def documenten_van_zaak(zaak_id: int):
    with get_db() as conn:
        return _rows(conn,
            "SELECT * FROM documenten WHERE zaak_id=? ORDER BY created_at DESC",
            (zaak_id,))


def document_van_stuk(stuk_id: int):
    with get_db() as conn:
        return _row(conn,
            "SELECT * FROM documenten WHERE stuk_id=? ORDER BY created_at DESC LIMIT 1",
            (stuk_id,))


def document_velden_opslaan(document_id: int, velden_json: str,
                            status: str = 'bevestigd') -> None:
    with get_db() as conn:
        conn.execute("UPDATE documenten SET velden_json=?, status=?, updated_at=? WHERE id=?",
                     (velden_json, status, _now(), document_id))


def document_verwijderen(document_id: int):
    """Geeft het pad naar het versleutelde bestand terug zodat de aanroeper
    het van schijf kan verwijderen."""
    with get_db() as conn:
        r = _row(conn, "SELECT pad_enc, stuk_id FROM documenten WHERE id=?", (document_id,))
        if not r:
            return None
        conn.execute("UPDATE stukken SET document_id=NULL WHERE document_id=?", (document_id,))
        conn.execute("DELETE FROM documenten WHERE id=?", (document_id,))
        return r['pad_enc']


# ── Taken ────────────────────────────────────────────────────────────────────

def taken_ophalen(zaak_id: int):
    with get_db() as conn:
        return _rows(conn, "SELECT * FROM taken WHERE zaak_id=? ORDER BY status,deadline,id",
                     (zaak_id,))


def taak_toevoegen(zaak_id: int, omschrijving: str, deadline: str = None) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO taken (zaak_id,omschrijving,deadline) VALUES (?,?,?)",
            (zaak_id, omschrijving, deadline or None))
        return cur.lastrowid


def taak_toggle(taak_id: int) -> str:
    with get_db() as conn:
        huidig = _row(conn, "SELECT status FROM taken WHERE id=?", (taak_id,))
        nieuw  = 'gedaan' if huidig['status'] == 'open' else 'open'
        conn.execute("UPDATE taken SET status=?, updated_at=? WHERE id=?",
                     (nieuw, _now(), taak_id))
    return nieuw


def taak_verwijderen(taak_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM taken WHERE id=?", (taak_id,))


# ── Notities ─────────────────────────────────────────────────────────────────

def notities_ophalen(zaak_id: int):
    with get_db() as conn:
        return _rows(conn, "SELECT * FROM notities WHERE zaak_id=? ORDER BY created_at DESC",
                     (zaak_id,))


def notitie_toevoegen(zaak_id: int, tekst: str) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO notities (zaak_id,tekst) VALUES (?,?)",
            (zaak_id, tekst))
        return cur.lastrowid


def notitie_verwijderen(notitie_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM notities WHERE id=?", (notitie_id,))


# ── Signaleringen ─────────────────────────────────────────────────────────────

def signaleringen_ophalen(zaak_id: int):
    with get_db() as conn:
        return _rows(conn,
            "SELECT * FROM signaleringen WHERE zaak_id=? ORDER BY ernst DESC, created_at DESC",
            (zaak_id,))


def signalering_toevoegen(zaak_id: int, stype: str,
                          bericht: str, ernst: str = 'info') -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO signaleringen (zaak_id,type,bericht,ernst) VALUES (?,?,?,?)",
            (zaak_id, stype, bericht, ernst))
        return cur.lastrowid


def signalering_oplossen(sig_id: int) -> None:
    with get_db() as conn:
        conn.execute("UPDATE signaleringen SET opgelost=1 WHERE id=?", (sig_id,))


# ── Logboek ──────────────────────────────────────────────────────────────────

def logboek_schrijven(zaak_id: int | None, actie: str, details: str = None) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO logboek (zaak_id,actie,details) VALUES (?,?,?)",
            (zaak_id, actie, details))


def logboek_ophalen(zaak_id: int | None = None, limit: int = 200):
    with get_db() as conn:
        if zaak_id:
            return _rows(conn,
                "SELECT * FROM logboek WHERE zaak_id=? ORDER BY timestamp DESC LIMIT ?",
                (zaak_id, limit))
        return _rows(conn,
            "SELECT * FROM logboek ORDER BY timestamp DESC LIMIT ?", (limit,))


# ── Instellingen ─────────────────────────────────────────────────────────────

def instelling_ophalen(sleutel: str, normjaar: int | None = None, default=None):
    with get_db() as conn:
        r = _row(conn,
            "SELECT waarde FROM instellingen WHERE sleutel=? AND (normjaar=? OR normjaar IS NULL) LIMIT 1",
            (sleutel, normjaar))
    return r['waarde'] if r else default


def instelling_opslaan(sleutel: str, waarde: str, normjaar: int | None = None) -> None:
    with get_db() as conn:
        if normjaar is None:
            # ON CONFLICT werkt niet met NULL in SQLite → eerst bijwerken, anders invoegen.
            cur = conn.execute(
                "UPDATE instellingen SET waarde=? WHERE sleutel=? AND normjaar IS NULL",
                (waarde, sleutel))
            if cur.rowcount == 0:
                conn.execute(
                    "INSERT INTO instellingen (sleutel, waarde, normjaar) VALUES (?,?,NULL)",
                    (sleutel, waarde))
        else:
            conn.execute("""
                INSERT INTO instellingen (sleutel, waarde, normjaar)
                VALUES (?,?,?)
                ON CONFLICT(sleutel, normjaar) DO UPDATE SET waarde=excluded.waarde
            """, (sleutel, waarde, normjaar))


def alle_instellingen_ophalen(normjaar: int | None = None):
    with get_db() as conn:
        return _rows(conn,
            "SELECT * FROM instellingen WHERE normjaar=? OR normjaar IS NULL ORDER BY sleutel",
            (normjaar,))


# ── Export ───────────────────────────────────────────────────────────────────

def zaak_volledig_ophalen(zaak_id: int) -> dict:
    """Alle data van één zaak als dict (voor export/rapport)."""
    with get_db() as conn:
        zaak     = dict(_row(conn, "SELECT * FROM zaken WHERE id=?", (zaak_id,)))
        k1       = dict(_row(conn, "SELECT * FROM klanten WHERE id=?", (zaak['aanvrager1_id'],)))
        k2       = dict(_row(conn, "SELECT * FROM klanten WHERE id=?", (zaak['aanvrager2_id'],))) \
                   if zaak.get('aanvrager2_id') else None
        stukken  = [dict(r) for r in _rows(conn, "SELECT * FROM stukken WHERE zaak_id=?", (zaak_id,))]
        taken    = [dict(r) for r in _rows(conn, "SELECT * FROM taken WHERE zaak_id=?", (zaak_id,))]
        notities = [dict(r) for r in _rows(conn, "SELECT * FROM notities WHERE zaak_id=?", (zaak_id,))]
    return dict(zaak=zaak, klant1=k1, klant2=k2,
                stukken=stukken, taken=taken, notities=notities)
