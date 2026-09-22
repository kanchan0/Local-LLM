import pytest

from app.security import hash_password, verify_password


def test_password_hashing():
    password_hash = hash_password("a-long-test-password")
    assert password_hash != "a-long-test-password"
    assert verify_password("a-long-test-password", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_short_password_rejected():
    with pytest.raises(ValueError):
        hash_password("short")
