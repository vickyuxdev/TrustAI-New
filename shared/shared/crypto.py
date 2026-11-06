"""
shared/crypto.py
AES-256-GCM symmetric encryption for storing connector credentials in the DB.
The raw key is read from TRUSTAI_ENCRYPTION_KEY env var (32-byte base64 string).
In production, rotate this key and migrate existing credentials.
"""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_DEV_KEY = b"trustai-dev-enc-key-32-bytes!!!!"  # 32 bytes exactly


def _get_key() -> bytes:
    """Return 32-byte encryption key."""
    raw = os.environ.get("TRUSTAI_ENCRYPTION_KEY", "")
    if raw:
        try:
            decoded = base64.urlsafe_b64decode(raw.encode())
            return decoded[:32].ljust(32, b"\x00")
        except Exception:
            pass
    return _DEV_KEY


def encrypt_secret(plaintext: str) -> str:
    """
    Encrypt a plaintext secret string.
    Returns a URL-safe base64 string: nonce(12) + ciphertext.
    """
    if not plaintext:
        return ""
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """
    Decrypt a ciphertext string produced by encrypt_secret().
    Returns the original plaintext. Raises ValueError on failure.
    """
    if not ciphertext:
        return ""
    try:
        key = _get_key()
        aesgcm = AESGCM(key)
        data = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
        nonce, ct = data[:12], data[12:]
        return aesgcm.decrypt(nonce, ct, None).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Failed to decrypt secret: {exc}") from exc
