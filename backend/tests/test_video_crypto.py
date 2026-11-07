import pytest

from backend.app.services.video_crypto import (
    CHUNK_SIZE,
    HEADER,
    VideoCryptoError,
    decrypt_video_range,
    decrypt_video_to_file,
    encrypt_video_file,
    unwrap_video_key,
)


def unwrap(video_id: str, passkey: str, metadata: dict) -> bytes:
    return unwrap_video_key(
        video_id=video_id,
        passkey=passkey,
        salt=metadata["salt"],
        wrapped_key=metadata["wrapped_key"],
        wrap_nonce=metadata["wrap_nonce"],
        crypto_version=metadata["crypto_version"],
        crypto_algorithm=metadata["crypto_algorithm"],
        key_wrap_algorithm=metadata["key_wrap_algorithm"],
        kdf_time_cost=metadata["kdf_time_cost"],
        kdf_memory_cost_kib=metadata["kdf_memory_cost_kib"],
        kdf_parallelism=metadata["kdf_parallelism"],
    )


def test_chunked_video_round_trip_and_cross_chunk_range(tmp_path):
    source = tmp_path / "source.bin"
    encrypted = tmp_path / "original.enc"
    restored = tmp_path / "restored.bin"
    plaintext = bytes(index % 251 for index in range(CHUNK_SIZE * 2 + 37))
    source.write_bytes(plaintext)

    data_key, metadata = encrypt_video_file(
        source,
        encrypted,
        video_id="case_" + "a" * 32,
        passkey="a unique video passkey",
    )
    decrypt_video_to_file(
        encrypted,
        restored,
        video_id="case_" + "a" * 32,
        data_key=data_key,
        expected_size=metadata["encrypted_size"],
    )

    assert restored.read_bytes() == plaintext
    start = CHUNK_SIZE - 7
    end = CHUNK_SIZE + 12
    assert b"".join(
        decrypt_video_range(
            encrypted,
            video_id="case_" + "a" * 32,
            data_key=data_key,
            start=start,
            end=end,
        )
    ) == plaintext[start : end + 1]


def test_video_key_wrap_rejects_wrong_passkey_and_binds_video_id(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"private video bytes")
    video_id = "case_" + "b" * 32
    encrypted = tmp_path / "original.enc"
    data_key, metadata = encrypt_video_file(
        source,
        encrypted,
        video_id=video_id,
        passkey="correct unique passkey",
    )

    assert unwrap(video_id, "correct unique passkey", metadata) == data_key
    with pytest.raises(VideoCryptoError):
        unwrap(video_id, "incorrect unique passkey", metadata)
    with pytest.raises(VideoCryptoError):
        unwrap("case_" + "c" * 32, "correct unique passkey", metadata)


def test_each_video_gets_a_distinct_random_key_and_salt(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"same video content")
    first_key, first_metadata = encrypt_video_file(
        source,
        tmp_path / "first.enc",
        video_id="case_" + "d" * 32,
        passkey="same unique passkey",
    )
    second_key, second_metadata = encrypt_video_file(
        source,
        tmp_path / "second.enc",
        video_id="case_" + "e" * 32,
        passkey="same unique passkey",
    )

    assert first_key != second_key
    assert first_metadata["salt"] != second_metadata["salt"]
    assert (tmp_path / "first.enc").read_bytes() != (tmp_path / "second.enc").read_bytes()


def test_tampered_chunk_fails_authentication(tmp_path):
    source = tmp_path / "source.bin"
    encrypted = tmp_path / "original.enc"
    plaintext = b"a" * (CHUNK_SIZE + 10)
    source.write_bytes(plaintext)
    data_key, _ = encrypt_video_file(
        source,
        encrypted,
        video_id="case_" + "f" * 32,
        passkey="another unique passkey",
    )

    with encrypted.open("r+b") as output:
        output.seek(HEADER.size + 10)
        original_byte = output.read(1)
        output.seek(HEADER.size + 10)
        output.write(bytes([original_byte[0] ^ 1]))

    with pytest.raises(VideoCryptoError, match="authentication"):
        list(
            decrypt_video_range(
                encrypted,
                video_id="case_" + "f" * 32,
                data_key=data_key,
                start=0,
                end=20,
            )
        )
