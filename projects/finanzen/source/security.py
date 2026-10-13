"""
security.py — wachtwoord, versleuteling, sessie-beheer
Alle klantdata blijft lokaal; gevoelige velden worden met Fernet versleuteld opgeslagen.
"""
from __future__ import annotations
import os, json, base64, zipfile
from datetime import datetime
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import bcrypt

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, 'data')
CFG_PATH  = os.path.join(DATA_DIR, 'config.json')
DOCS_DIR  = os.path.join(DATA_DIR, 'documenten')

# In-memory sessiesleutel — verdwijnt bij afsluiten of vergrendelen
_session_key: bytes | None = None


# ── Configuratie ────────────────────────────────────────────────────────────

def is_setup_done() -> bool:
    return os.path.exists(CFG_PATH)


def setup_password(password: str) -> None:
    """Eerste keer: wachtwoord instellen, salt genereren, config opslaan."""
    os.makedirs(DATA_DIR, exist_ok=True)
    salt      = os.urandom(32)
    pw_hash   = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))
    # Genereer ook een Flask secret key (eenmalig, voor sessie-cookies)
    flask_key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    cfg = {
        'password_hash': pw_hash.decode(),
        'kdf_salt':      base64.b64encode(salt).decode(),
        'flask_secret':  flask_key,
    }
    with open(CFG_PATH, 'w') as f:
        json.dump(cfg, f, indent=2)


def get_flask_secret() -> str:
    if not is_setup_done():
        return os.urandom(32).hex()   # tijdelijk, vóór setup
    with open(CFG_PATH) as f:
        return json.load(f)['flask_secret']


# ── Ontgrendelen / vergrendelen ──────────────────────────────────────────────

def unlock(password: str) -> bool:
    """Wachtwoord controleren en sessiesleutel in geheugen laden."""
    global _session_key
    if not is_setup_done():
        return False
    with open(CFG_PATH) as f:
        cfg = json.load(f)
    if not bcrypt.checkpw(password.encode(), cfg['password_hash'].encode()):
        return False
    salt      = base64.b64decode(cfg['kdf_salt'])
    kdf       = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                            salt=salt, iterations=480_000)
    _session_key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return True


def lock() -> None:
    global _session_key
    _session_key = None


def is_unlocked() -> bool:
    return _session_key is not None


# ── Veldversleuteling (voor BSN en documentnummers) ──────────────────────────

def _fernet() -> Fernet:
    if not _session_key:
        raise RuntimeError("Applicatie is vergrendeld.")
    return Fernet(_session_key)


def encrypt_field(value: str) -> str:
    """Versleutel een gevoelig tekstveld voor opslag in de database."""
    if not value:
        return ''
    return _fernet().encrypt(value.encode()).decode()


def decrypt_field(value: str) -> str:
    """Ontsleutel een gevoelig tekstveld voor weergave."""
    if not value:
        return ''
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, Exception):
        return '(kan niet ontsleutelen)'


# ── Documentbestanden (versleuteld op schijf) ────────────────────────────────

def encrypt_bytes(raw: bytes) -> bytes:
    """Versleutel ruwe bestandsbytes (voor documentopslag)."""
    return _fernet().encrypt(raw)


def decrypt_bytes(token: bytes) -> bytes:
    """Ontsleutel bestandsbytes."""
    return _fernet().decrypt(token)


def save_encrypted_document(raw: bytes) -> str:
    """Slaat versleutelde bestandsbytes op in DOCS_DIR onder een willekeurige
    naam. Geeft het absolute pad naar het .enc-bestand terug."""
    import uuid
    os.makedirs(DOCS_DIR, exist_ok=True)
    pad = os.path.join(DOCS_DIR, uuid.uuid4().hex + '.enc')
    with open(pad, 'wb') as f:
        f.write(encrypt_bytes(raw))
    return pad


def read_encrypted_document(pad: str) -> bytes:
    """Leest en ontsleutelt een eerder opgeslagen documentbestand."""
    with open(pad, 'rb') as f:
        return decrypt_bytes(f.read())


# ── Back-up ──────────────────────────────────────────────────────────────────

def create_backup(dest_dir: str) -> str:
    """
    Maakt een versleutelde ZIP van de data-map en slaat die op in dest_dir.
    De ZIP is alleen te openen met de applicatie (Fernet-versleuteld).
    Geeft het volledige pad naar het back-upbestand terug.
    """
    os.makedirs(dest_dir, exist_ok=True)
    ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
    zip_path = os.path.join(dest_dir, f'finanzen_backup_{ts}.zip')
    enc_path = zip_path + '.enc'

    # Pak alle data-bestanden in
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(DATA_DIR):
            for fname in files:
                fp     = os.path.join(root, fname)
                arcnm  = os.path.relpath(fp, DATA_DIR)
                zf.write(fp, arcnm)

    # Versleutel de ZIP
    with open(zip_path, 'rb') as f:
        raw = f.read()
    encrypted = _fernet().encrypt(raw)
    with open(enc_path, 'wb') as f:
        f.write(encrypted)

    # Verwijder onversleutelde ZIP
    os.remove(zip_path)
    return enc_path
