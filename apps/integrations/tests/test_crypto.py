from apps.integrations.skylight import crypto


def test_encrypt_decrypt_roundtrip():
    ciphertext = crypto.encrypt("hunter2")
    assert ciphertext != "hunter2"
    assert crypto.decrypt(ciphertext) == "hunter2"


def test_encrypt_is_not_deterministic_but_decrypts_the_same():
    a = crypto.encrypt("hunter2")
    b = crypto.encrypt("hunter2")
    assert a != b
    assert crypto.decrypt(a) == crypto.decrypt(b) == "hunter2"
