import hashlib


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
