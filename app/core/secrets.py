from app.config import get_settings

_s = get_settings()


def signing_keys() -> list[str]:
    keys = [_s.secret_key]
    if _s.secret_key_previous:
        keys.append(_s.secret_key_previous)
    return keys


def active_key() -> str:
    return _s.secret_key


def verify_keys() -> list[str]:
    return signing_keys()
