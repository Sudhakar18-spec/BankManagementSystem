import hashlib
import hmac
import os


def hash_pin(pin: str, salt_hex: str | None = None):
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 100_000)
    return digest.hex(), salt.hex()


def verify_pin(pin: str, pin_hash: str, salt_hex: str) -> bool:
    candidate, _ = hash_pin(pin, salt_hex)
    return hmac.compare_digest(candidate, pin_hash)