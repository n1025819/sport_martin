from pathlib import Path


def _fernet(key):
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.strip().encode("ascii"))
    except Exception as exc:
        raise RuntimeError("GARMIN_TOKEN_KEY 格式錯誤，請使用 garmin_login.py 產生的完整值") from exc


def encrypt_bytes(data, key):
    return _fernet(key).encrypt(data)


def decrypt_bytes(data, key):
    try:
        return _fernet(key).decrypt(data)
    except Exception as exc:
        raise RuntimeError("Garmin 權杖解密失敗；請確認 GARMIN_TOKEN_KEY 是否正確") from exc


def encrypt_file(source, destination, key):
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(encrypt_bytes(source.read_bytes(), key))


def decrypt_file(source, destination, key):
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(decrypt_bytes(source.read_bytes(), key))
