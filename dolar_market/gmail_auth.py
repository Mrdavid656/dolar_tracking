"""Create the send-only Gmail credential and store it in the repository's secrets.

Usage: python -m dolar_market.gmail_auth CLIENT_SECRET_JSON [OWNER/REPOSITORY]

CLIENT_SECRET_JSON is the file downloaded from Google Cloud for an OAuth client of
type "Desktop app". The script opens the browser so you can approve one permission,
"Send email on your behalf", and then saves GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and
GMAIL_REFRESH_TOKEN as secrets of the repository through the `gh` CLI. The values
are never printed. Without a repository argument it prints them instead.

Run it yourself in a terminal: it needs your browser.
"""

import json
import secrets
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .gmail_api import SEND_SCOPE, TIMEOUT, TOKEN_URL

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def read_client(path: str) -> tuple[str, str]:
    """Client id and secret from the JSON file Google Cloud provides."""
    client = json.loads(Path(path).read_text(encoding="utf-8"))["installed"]
    return client["client_id"], client["client_secret"]


def consent_url(client_id: str, redirect_uri: str, state: str) -> str:
    query = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SEND_SCOPE,
        "access_type": "offline",  # ask for a refresh token
        "prompt": "consent",  # always return one, even on a repeated approval
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(query)}"


def wait_for_code(server: HTTPServer, state: str) -> str:
    """Serve one request, the browser coming back from Google, and return its code."""
    received: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            received.update({key: values[0] for key, values in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Done. You can close this tab and return to the terminal.".encode())

        def log_message(self, *args):  # keep the code out of the terminal
            pass

    server.RequestHandlerClass = Handler
    while "code" not in received and "error" not in received:
        server.handle_request()
    if received.get("state") != state or "code" not in received:
        raise SystemExit(f"Authorisation failed: {received.get('error', 'unexpected response')}")
    return received["code"]


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> str:
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["refresh_token"]


def store_secret(repository: str, name: str, value: str) -> None:
    """Save one secret with the gh CLI, passing the value on stdin so it is never shown."""
    subprocess.run(["gh", "secret", "set", name, "--repo", repository], input=value, text=True, check=True)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    client_id, client_secret = read_client(sys.argv[1])
    repository = sys.argv[2] if len(sys.argv) > 2 else None

    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    state = secrets.token_urlsafe(16)
    url = consent_url(client_id, redirect_uri, state)
    print("Opening the browser. If it does not open, visit:\n" + url)
    webbrowser.open(url)
    refresh_token = exchange_code(client_id, client_secret, wait_for_code(server, state), redirect_uri)
    server.server_close()

    values = {
        "GMAIL_CLIENT_ID": client_id,
        "GMAIL_CLIENT_SECRET": client_secret,
        "GMAIL_REFRESH_TOKEN": refresh_token,
    }
    if repository:
        for name, value in values.items():
            store_secret(repository, name, value)
        print(f"Stored {', '.join(values)} as secrets of {repository}.")
    else:
        print("\n".join(f"{name}={value}" for name, value in values.items()))


if __name__ == "__main__":
    main()
