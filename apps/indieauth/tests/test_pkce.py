import hashlib
from base64 import urlsafe_b64encode

from apps.indieauth.auth import generate_pkce_pair


def test_pkce_verifier_length():
    verifier, _ = generate_pkce_pair()
    # RFC 7636 requires code_verifier to be 43–128 characters
    assert 43 <= len(verifier) <= 128


def test_pkce_challenge_is_s256():
    verifier, challenge = generate_pkce_pair()
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert challenge == expected


def test_pkce_challenge_has_no_padding():
    _, challenge = generate_pkce_pair()
    assert "=" not in challenge


def test_pkce_pairs_are_unique():
    pairs = {generate_pkce_pair()[0] for _ in range(20)}
    assert len(pairs) == 20
