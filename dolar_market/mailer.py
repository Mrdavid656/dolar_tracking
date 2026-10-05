"""Send a Gmail summary of the latest reading in data/rates.csv.

Usage:
    python -m dolar_market.mailer            # send the email
    python -m dolar_market.mailer --preview  # only write email_preview.html

Environment variables: GMAIL_USER, GMAIL_APP_PASSWORD, MAIL_TO (optional,
defaults to GMAIL_USER; accepts several comma-separated recipients) and
MAIL_LANG (optional, "es" or "en"; defaults to "es").
"""

import os
import smtplib
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import NamedTuple

from .models import Quote, Reading
from .sources import SOURCES
from .storage import read_readings

TD = 'style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right"'
TD_LEFT = 'style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:left"'
BEST_STYLE = "font-weight:bold;color:#067647"
NO_DATA = Quote()
DEFAULT_LANG = "es"

# User-facing text, one entry per language. Everything the reader sees lives here.
TEXTS: Mapping[str, Mapping[str, str]] = {
    "es": {
        "title": "Dólar en bancos de Bolivia",
        "reading": "Lectura del {date} · Oficial BCB: Bs {official}",
        "bank": "Banco",
        "buy": "Compra",
        "sell": "Venta",
        "note": (
            "En verde: el banco que más paga por tu dólar (compra)\n"
            "y el que lo vende más barato (venta). Las flechas comparan con la lectura anterior."
        ),
        "missing": "Sin datos en esta lectura: {banks}",
        "subject": "Dólar Bolivia {date}: venta desde Bs {sell}, compra hasta Bs {buy}",
        "plain": "Tu cliente de correo no muestra HTML.",
    },
    "en": {
        "title": "Dollar at Bolivian banks",
        "reading": "Reading from {date} · BCB official: Bs {official}",
        "bank": "Bank",
        "buy": "Buy",
        "sell": "Sell",
        "note": (
            "In green: the bank that pays the most for your dollar (buy)\n"
            "and the one that sells it cheapest (sell). Arrows compare with the previous reading."
        ),
        "missing": "No data in this reading: {banks}",
        "subject": "Bolivia dollar {date}: sell from Bs {sell}, buy up to Bs {buy}",
        "plain": "Your email client does not display HTML.",
    },
}


class Email(NamedTuple):
    subject: str
    html: str
    plain: str


# --- Pure functions: from readings to HTML ---------------------------------------


def fmt(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "—"


def official_of(reading: Reading) -> float | None:
    return next((q.official for q in reading.banks.values() if q.official is not None), None)


def priced_banks(reading: Reading) -> tuple[tuple[str, Quote], ...]:
    """Banks that publish buy or sell, from the cheapest seller to the most expensive."""
    banks = ((b, q) for b, q in reading.banks.items() if q.buy is not None or q.sell is not None)
    return tuple(sorted(banks, key=lambda pair: (pair[1].sell is None, pair[1].sell or 0, pair[0])))


def missing_banks(reading: Reading, sources: Iterable[str]) -> tuple[str, ...]:
    return tuple(bank for bank in sources if bank not in reading.banks)


def change_html(current: float | None, previous: float | None) -> str:
    if current is None or previous is None or current == previous:
        return ""
    color, arrow = ("#b42318", "▲") if current > previous else ("#067647", "▼")
    return f' <span style="color:{color};font-size:12px">{arrow} {abs(current - previous):.2f}</span>'


def cell_html(value: float | None, previous: float | None, best: float | None) -> str:
    style = BEST_STYLE if value is not None and value == best else ""
    return f'<td {TD}><span style="{style}">{fmt(value)}</span>{change_html(value, previous)}</td>'


def row_html(bank: str, current: Quote, previous: Quote, max_buy, min_sell) -> str:
    return (
        f"<tr><td {TD_LEFT}>{bank}</td>"
        f"{cell_html(current.buy, previous.buy, max_buy)}"
        f"{cell_html(current.sell, previous.sell, min_sell)}</tr>"
    )


def notice_html(missing: Sequence[str], text: Mapping[str, str]) -> str:
    if not missing:
        return ""
    return f'<p style="color:#b42318">{text["missing"].format(banks=", ".join(missing))}</p>'


def build(readings: Sequence[Reading], sources: Iterable[str], lang: str = DEFAULT_LANG) -> Email:
    """Build the email for the latest reading, compared with the previous one."""
    text = TEXTS.get(lang, TEXTS[DEFAULT_LANG])
    latest = readings[-1]
    previous = readings[-2].banks if len(readings) > 1 else {}
    date = datetime.fromisoformat(latest.timestamp).strftime("%d/%m/%Y %H:%M")
    banks = priced_banks(latest)
    min_sell = min((q.sell for _, q in banks if q.sell is not None), default=None)
    max_buy = max((q.buy for _, q in banks if q.buy is not None), default=None)
    rows = "".join(row_html(bank, q, previous.get(bank, NO_DATA), max_buy, min_sell) for bank, q in banks)
    heading = text["reading"].format(date=date, official=fmt(official_of(latest)))
    html = f"""<div style="font-family:Arial,Helvetica,sans-serif;color:#111827;max-width:520px">
<h2 style="margin:0 0 4px">{text["title"]}</h2>
<p style="margin:0 0 16px;color:#6b7280">{heading}</p>
<table style="border-collapse:collapse;width:100%">
<tr><th {TD_LEFT}>{text["bank"]}</th><th {TD}>{text["buy"]}</th><th {TD}>{text["sell"]}</th></tr>
{rows}
</table>
<p style="color:#6b7280;font-size:12px">{text["note"]}</p>
{notice_html(missing_banks(latest, sources), text)}</div>"""
    subject = text["subject"].format(date=date, sell=fmt(min_sell), buy=fmt(max_buy))
    return Email(subject, html, text["plain"])


def to_message(email: Email, sender: str, recipient: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = email.subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(email.plain)
    message.add_alternative(email.html, subtype="html")
    return message


# --- Effects: disk, environment and network --------------------------------------


def send(message: EmailMessage, user: str, password: str) -> None:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, password)
        smtp.send_message(message)


def main() -> None:
    email = build(read_readings(), SOURCES, os.environ.get("MAIL_LANG") or DEFAULT_LANG)
    if "--preview" in sys.argv:
        Path("email_preview.html").write_text(email.html, encoding="utf-8")
        print(email.subject)
        return
    user = os.environ["GMAIL_USER"]
    recipient = os.environ.get("MAIL_TO") or user
    send(to_message(email, user, recipient), user, os.environ["GMAIL_APP_PASSWORD"])
    print(f"Email sent to {recipient}")


if __name__ == "__main__":
    main()
