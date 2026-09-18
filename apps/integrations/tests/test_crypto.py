from apps.integrations import crypto


def test_encrypt_decrypt_round_trips():
    ciphertext = crypto.encrypt("a-refresh-token")
    assert ciphertext != "a-refresh-token"
    assert crypto.decrypt(ciphertext) == "a-refresh-token"
