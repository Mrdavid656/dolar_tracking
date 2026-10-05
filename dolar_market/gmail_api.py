"""Send email through the Gmail API with a credential that can only send.

An app password opens the whole mailbox to whoever holds it. The OAuth credential
used here is limited to the `gmail.send` scope: it can send messages as the account
and nothing else. Create it once with `python -m dolar_market.gmail_auth`.
"""

import base64
from collections.abc import Sequence
from email.message import EmailMessage

import requests

SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
TIMEOUT = 30


def to_raw(message: EmailMessage) -> str:
    """The message encoded as the API expects it: base64url of its full source."""
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def fetch_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    """Exchange the long-lived refresh token for a short-lived access token."""
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def send_batch(messages: Sequence[EmailMessage], access_token: str) -> tuple[int, int]:
    """Send a few messages. Returns (delivered, refused)."""
    delivered = refused = 0
    for message in messages:
        response = requests.post(
            SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": to_raw(message)},
            timeout=TIMEOUT,
        )
        if response.status_code == 400:  # malformed recipient: skip it, keep going
            refused += 1
            continue
        response.raise_for_status()
        delivered += 1
    return delivered, refused
