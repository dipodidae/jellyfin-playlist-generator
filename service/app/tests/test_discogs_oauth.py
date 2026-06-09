from app.ingestion.discogs_oauth import build_oauth_header


def test_request_token_header_plaintext_signature():
    h = build_oauth_header(
        consumer_key="CK", consumer_secret="CS",
        token=None, token_secret=None,
        callback="https://x/cb", verifier=None,
        nonce="NONCE", timestamp="123",
    )
    assert 'oauth_consumer_key="CK"' in h
    assert 'oauth_signature_method="PLAINTEXT"' in h
    assert 'oauth_signature="CS&"' in h          # no token secret yet
    assert 'oauth_callback="https%3A%2F%2Fx%2Fcb"' in h
    assert 'oauth_nonce="NONCE"' in h
    assert 'oauth_timestamp="123"' in h


def test_access_token_header_includes_token_and_verifier():
    h = build_oauth_header(
        consumer_key="CK", consumer_secret="CS",
        token="RT", token_secret="RTS",
        callback=None, verifier="VERIF",
        nonce="N", timestamp="1",
    )
    assert 'oauth_token="RT"' in h
    assert 'oauth_verifier="VERIF"' in h
    assert 'oauth_signature="CS&RTS"' in h        # consumer secret & token secret
