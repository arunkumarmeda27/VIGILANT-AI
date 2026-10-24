from app.core.security import get_password_hash, verify_password

def test_password_hashing():
    password = "my_secure_password_123"

    # Test 1: Correct password succeeds
    hash1 = get_password_hash(password)
    assert verify_password(password, hash1) is True

    # Test 2: Incorrect password fails
    assert verify_password("wrong_password", hash1) is False

    # Test 3: Salting - two hashes of the same password must differ
    hash2 = get_password_hash(password)
    assert hash1 != hash2, "Hashes should be different due to salting"
    assert verify_password(password, hash2) is True

    # Test 4: Long passwords (over 72 bytes) work correctly
    long_password = "a" * 100
    long_hash = get_password_hash(long_password)
    assert verify_password(long_password, long_hash) is True
    assert verify_password("a" * 99, long_hash) is False

def test_invalid_hash_format():
    # Test 5: Invalid hash format doesn't crash
    assert verify_password("password", "not-a-real-hash") is False
