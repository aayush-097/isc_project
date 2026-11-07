import secrets
import struct
from collections.abc import Iterator
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


CRYPTO_VERSION = 1
CRYPTO_ALGORITHM = "AES-256-GCM-CHUNKED"
KEY_WRAP_ALGORITHM = "ARGON2ID-AES-256-GCM"
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST_KIB = 64 * 1024
ARGON2_PARALLELISM = 1
ARGON2_KEY_LENGTH = 32
CHUNK_SIZE = 1024 * 1024
HEADER = struct.Struct(">4sIQ8s")
CHUNK_AAD = struct.Struct(">QI")
MAGIC = b"FSV1"
TAG_SIZE = 16
KEY_WRAP_AAD_PREFIX = b"framesafe-video-key:v1:"


class VideoCryptoError(Exception):
    """Raised when an encrypted video or its wrapped key cannot be authenticated."""


def _derive_wrapping_key(passkey: str, salt: bytes) -> bytes:
    return hash_secret_raw(
        secret=passkey.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_KEY_LENGTH,
        type=Type.ID,
    )


def encrypt_video_file(
    source_path: Path,
    encrypted_path: Path,
    *,
    video_id: str,
    passkey: str,
) -> tuple[bytes, dict[str, bytes | int | str]]:
    """Encrypt a video in authenticated chunks and wrap its random AES key."""
    data_key = secrets.token_bytes(32)
    salt = secrets.token_bytes(16)
    wrap_nonce = secrets.token_bytes(12)
    wrapping_key = _derive_wrapping_key(passkey, salt)
    wrapped_key = AESGCM(wrapping_key).encrypt(
        wrap_nonce,
        data_key,
        KEY_WRAP_AAD_PREFIX + video_id.encode("ascii"),
    )
    file_size = source_path.stat().st_size
    nonce_prefix = secrets.token_bytes(8)
    header = HEADER.pack(MAGIC, CHUNK_SIZE, file_size, nonce_prefix)
    encrypted_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with source_path.open("rb") as source, encrypted_path.open("xb") as destination:
            destination.write(header)
            aes = AESGCM(data_key)
            index = 0
            while index * CHUNK_SIZE < file_size:
                remaining = file_size - index * CHUNK_SIZE
                plain_chunk = source.read(min(CHUNK_SIZE, remaining))
                if not plain_chunk:
                    raise OSError("The upload changed while it was being encrypted.")
                nonce = nonce_prefix + index.to_bytes(4, "big")
                aad = (
                    KEY_WRAP_AAD_PREFIX
                    + video_id.encode("ascii")
                    + header
                    + CHUNK_AAD.pack(index, len(plain_chunk))
                )
                destination.write(aes.encrypt(nonce, plain_chunk, aad))
                index += 1
            if source.read(1):
                raise OSError("The upload changed while it was being encrypted.")
    except Exception:
        encrypted_path.unlink(missing_ok=True)
        raise

    return data_key, {
        "salt": salt,
        "wrapped_key": wrapped_key,
        "wrap_nonce": wrap_nonce,
        "crypto_version": CRYPTO_VERSION,
        "crypto_algorithm": CRYPTO_ALGORITHM,
        "key_wrap_algorithm": KEY_WRAP_ALGORITHM,
        "kdf_time_cost": ARGON2_TIME_COST,
        "kdf_memory_cost_kib": ARGON2_MEMORY_COST_KIB,
        "kdf_parallelism": ARGON2_PARALLELISM,
        "encrypted_size": encrypted_path.stat().st_size,
    }


def unwrap_video_key(
    *,
    video_id: str,
    passkey: str,
    salt: bytes,
    wrapped_key: bytes,
    wrap_nonce: bytes,
    crypto_version: int,
    crypto_algorithm: str,
    key_wrap_algorithm: str,
    kdf_time_cost: int,
    kdf_memory_cost_kib: int,
    kdf_parallelism: int,
) -> bytes:
    if (
        crypto_version != CRYPTO_VERSION
        or crypto_algorithm != CRYPTO_ALGORITHM
        or key_wrap_algorithm != KEY_WRAP_ALGORITHM
        or kdf_time_cost != ARGON2_TIME_COST
        or kdf_memory_cost_kib != ARGON2_MEMORY_COST_KIB
        or kdf_parallelism != ARGON2_PARALLELISM
    ):
        raise VideoCryptoError("Video encryption metadata is unsupported.")
    wrapping_key = _derive_wrapping_key(passkey, salt)
    try:
        data_key = AESGCM(wrapping_key).decrypt(
            wrap_nonce,
            wrapped_key,
            KEY_WRAP_AAD_PREFIX + video_id.encode("ascii"),
        )
    except (InvalidTag, ValueError) as exc:
        raise VideoCryptoError("Video key authentication failed.") from exc
    if len(data_key) != 32:
        raise VideoCryptoError("Video key has an invalid length.")
    return data_key


def encrypted_video_size(encrypted_path: Path, expected_size: int | None = None) -> int:
    with encrypted_path.open("rb") as source:
        header_bytes = source.read(HEADER.size)
    if len(header_bytes) != HEADER.size:
        raise VideoCryptoError("Encrypted video header is incomplete.")
    magic, chunk_size, plain_size, _ = HEADER.unpack(header_bytes)
    if magic != MAGIC or chunk_size != CHUNK_SIZE or plain_size <= 0:
        raise VideoCryptoError("Encrypted video header is invalid.")
    chunk_count = (plain_size + chunk_size - 1) // chunk_size
    calculated_size = HEADER.size + plain_size + chunk_count * TAG_SIZE
    if encrypted_path.stat().st_size != calculated_size:
        raise VideoCryptoError("Encrypted video is incomplete or has unexpected data.")
    if expected_size is not None and expected_size != calculated_size:
        raise VideoCryptoError("Encrypted video metadata does not match the file.")
    return plain_size


def _decrypt_range(
    encrypted_path: Path,
    *,
    video_id: str,
    data_key: bytes,
    start: int,
    end: int,
) -> Iterator[bytes]:
    with encrypted_path.open("rb") as source:
        header_bytes = source.read(HEADER.size)
        if len(header_bytes) != HEADER.size:
            raise VideoCryptoError("Encrypted video header is incomplete.")
        magic, chunk_size, plain_size, nonce_prefix = HEADER.unpack(header_bytes)
        if magic != MAGIC or chunk_size != CHUNK_SIZE:
            raise VideoCryptoError("Encrypted video header is invalid.")
        if start < 0 or end < start or end >= plain_size:
            raise ValueError("The requested plaintext range is invalid.")
        chunk_count = (plain_size + chunk_size - 1) // chunk_size
        expected_file_size = HEADER.size + plain_size + chunk_count * TAG_SIZE
        if encrypted_path.stat().st_size != expected_file_size:
            raise VideoCryptoError("Encrypted video is incomplete or has unexpected data.")

        first_chunk = start // chunk_size
        last_chunk = end // chunk_size
        aes = AESGCM(data_key)
        for index in range(first_chunk, last_chunk + 1):
            plain_offset = index * chunk_size
            plain_length = min(chunk_size, plain_size - plain_offset)
            encrypted_offset = HEADER.size + index * (chunk_size + TAG_SIZE)
            source.seek(encrypted_offset)
            ciphertext = source.read(plain_length + TAG_SIZE)
            if len(ciphertext) != plain_length + TAG_SIZE:
                raise VideoCryptoError("Encrypted video chunk is incomplete.")
            nonce = nonce_prefix + index.to_bytes(4, "big")
            aad = (
                KEY_WRAP_AAD_PREFIX
                + video_id.encode("ascii")
                + header_bytes
                + CHUNK_AAD.pack(index, plain_length)
            )
            try:
                plaintext = aes.decrypt(nonce, ciphertext, aad)
            except (InvalidTag, ValueError) as exc:
                raise VideoCryptoError("Encrypted video chunk authentication failed.") from exc
            chunk_start = max(start - plain_offset, 0)
            chunk_end = min(end - plain_offset + 1, plain_length)
            yield plaintext[chunk_start:chunk_end]


def verify_video_range(
    encrypted_path: Path,
    *,
    video_id: str,
    data_key: bytes,
    start: int,
    end: int,
) -> int:
    plain_size = encrypted_video_size(encrypted_path)
    for _ in _decrypt_range(
        encrypted_path,
        video_id=video_id,
        data_key=data_key,
        start=start,
        end=end,
    ):
        pass
    return plain_size


def decrypt_video_range(
    encrypted_path: Path,
    *,
    video_id: str,
    data_key: bytes,
    start: int,
    end: int,
) -> Iterator[bytes]:
    yield from _decrypt_range(
        encrypted_path,
        video_id=video_id,
        data_key=data_key,
        start=start,
        end=end,
    )


def decrypt_video_to_file(
    encrypted_path: Path,
    destination_path: Path,
    *,
    video_id: str,
    data_key: bytes,
    expected_size: int | None = None,
) -> None:
    plain_size = encrypted_video_size(encrypted_path, expected_size)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination_path.open("xb") as destination:
            for chunk in _decrypt_range(
                encrypted_path,
                video_id=video_id,
                data_key=data_key,
                start=0,
                end=plain_size - 1,
            ):
                destination.write(chunk)
    except Exception:
        destination_path.unlink(missing_ok=True)
        raise
