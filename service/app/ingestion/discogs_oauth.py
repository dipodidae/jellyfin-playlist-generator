"""Discogs 3-legged OAuth 1.0a using the PLAINTEXT signature method.

Discogs permits PLAINTEXT over HTTPS, so the signature is simply
`consumer_secret&token_secret` and no base-string/HMAC is needed.
Flow: request_token -> user authorizes -> access_token.
"""

import logging
from urllib.parse import parse_qs, quote

import httpx

logger = logging.getLogger(__name__)

_REQUEST_TOKEN_URL = "https://api.discogs.com/oauth/request_token"
_AUTHORIZE_URL = "https://www.discogs.com/oauth/authorize"
_ACCESS_TOKEN_URL = "https://api.discogs.com/oauth/access_token"
_UA = "playlist-generator/1.0"


def _q(v: str) -> str:
    return quote(str(v), safe="")


def build_oauth_header(
    *, consumer_key: str, consumer_secret: str,
    token: str | None, token_secret: str | None,
    callback: str | None, verifier: str | None,
    nonce: str, timestamp: str,
) -> str:
    """Build an OAuth 1.0a Authorization header value (PLAINTEXT signature)."""
    signature = f"{consumer_secret}&{token_secret or ''}"
    params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce,
        "oauth_signature_method": "PLAINTEXT",
        "oauth_timestamp": timestamp,
        "oauth_version": "1.0",
    }
    if callback:
        params["oauth_callback"] = callback
    if token:
        params["oauth_token"] = token
    if verifier:
        params["oauth_verifier"] = verifier
    parts = ", ".join(f'{k}="{_q(v)}"' for k, v in params.items())
    # Signature is appended last, unencoded (PLAINTEXT method: consumer_secret&token_secret)
    parts += f', oauth_signature="{signature}"'
    return f"OAuth {parts}"


def _nonce_and_ts() -> tuple[str, str]:
    import time
    import uuid
    return uuid.uuid4().hex, str(int(time.time()))


async def fetch_request_token(consumer_key: str, consumer_secret: str, callback: str) -> dict:
    """Step 1: get a temporary request token + secret + the authorize URL."""
    nonce, ts = _nonce_and_ts()
    header = build_oauth_header(
        consumer_key=consumer_key, consumer_secret=consumer_secret,
        token=None, token_secret=None, callback=callback, verifier=None,
        nonce=nonce, timestamp=ts,
    )
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(_REQUEST_TOKEN_URL,
                             headers={"Authorization": header, "User-Agent": _UA})
    r.raise_for_status()
    data = {k: v[0] for k, v in parse_qs(r.text).items()}
    return {
        "oauth_token": data["oauth_token"],
        "oauth_token_secret": data["oauth_token_secret"],
        "authorize_url": f"{_AUTHORIZE_URL}?oauth_token={data['oauth_token']}",
    }


async def fetch_access_token(
    consumer_key: str, consumer_secret: str,
    request_token: str, request_token_secret: str, verifier: str,
) -> dict:
    """Step 3: exchange the authorized request token for a permanent access token."""
    nonce, ts = _nonce_and_ts()
    header = build_oauth_header(
        consumer_key=consumer_key, consumer_secret=consumer_secret,
        token=request_token, token_secret=request_token_secret,
        callback=None, verifier=verifier, nonce=nonce, timestamp=ts,
    )
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(_ACCESS_TOKEN_URL,
                              headers={"Authorization": header, "User-Agent": _UA})
    r.raise_for_status()
    data = {k: v[0] for k, v in parse_qs(r.text).items()}
    return {
        "oauth_token": data["oauth_token"],
        "oauth_token_secret": data["oauth_token_secret"],
    }
