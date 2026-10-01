import hashlib


def normalize(query: str) -> str:
    return " ".join(query.split()).lower()


def query_hash(query: str) -> str:
    return hashlib.sha256(normalize(query).encode("utf-8")).hexdigest()
