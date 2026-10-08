"""Send a Gmail summary of the latest reading in data/rates.csv.

Usage:
    python -m dolar_market.mailer            # send the email
    python -m dolar_market.mailer --preview  # only write email_preview.html
    python -m dolar_market.mailer --check    # only report who would receive it

Safeguards: nothing is sent when the latest reading is older than MAX_READING_AGE
(the email must never present stale prices as today's) or when the list exceeds
MAX_RECIPIENTS (a flooded sign-up form must not turn this account into a spammer).
Messages go out in small batches with a pause in between.

Environment variables:
    GMAIL_USER       the Gmail address that sends the email
    GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN
                     send-only Gmail API credential (see gmail_auth.py); preferred
    GMAIL_APP_PASSWORD  app password, used only when no API credential is set
    MAIL_TO          optional; comma-separated recipients who always get it
    SUBSCRIBERS_URL  optional; URL of the CSV with the sign-up form's responses
                     (a Google Sheet published to the web)
    UNSUBSCRIBE_URL  optional; link to the same form pre-filled to unsubscribe,
                     with "{email}" where the recipient's address goes
    MAIL_ONLY_TO     optional; send only to these addresses, ignoring the
                     subscribers (for trying the email out)
    MAIL_LANG        optional; "es" or "en" (defaults to "es")
    MAIL_MAX_RECIPIENTS  optional; overrides MAX_RECIPIENTS
    DASHBOARD_URL    optional; adds a button linking to the live dashboard

Subscribing and unsubscribing are both answers to one form. The responses are
read in order and the last answer of each address decides, so people manage their
own subscription and the list needs no upkeep. Each recipient gets an individual
message carrying a personal unsubscribe link. With no recipients configured the
email goes to GMAIL_USER.

The HTML mirrors the dashboard's dark board. Email clients run no scripts and
ignore most CSS, so the layout is built from tables with inline styles and the
chart from table cells sized in percentages.
"""

import csv
import io
import math
import os
import re
import smtplib
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

import requests

from . import gmail_api

from .analysis import (
    Deal,
    average_gap,
    best_buy,
    best_sell,
    missing_sources,
    official_of,
    parallel_of,
    priced_banks,
)
from .models import Quote, Reading
from .sources import PARALLEL_SOURCE, SOURCES
from .storage import read_readings

NO_DATA = Quote()
MAX_RECIPIENTS = 200
MAX_READING_AGE = timedelta(hours=6)
BATCH_SIZE = 10  # messages per connection
BATCH_PAUSE_SECONDS = 30  # wait between batches, to send at a gentle rate
DEFAULT_LANG = "es"
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# A form answer starting with one of these means "take me off the list".
UNSUBSCRIBE_WORDS = ("unsubscribe", "cancel", "baja", "darme de baja", "desuscri", "dejar de")

# The dashboard's dark palette.
PAGE = "#0d0f0e"
CARD = "#181a19"
INK = "#f4f6f3"
INK_2 = "#c0c5bf"
MUTED = "#898f89"
GRID = "#2a2d2b"
AXIS = "#3a3e3b"
ACCENT = "#6fcfb4"
PARALLEL_COLOR = "#a79df0"
BUY_COLOR = "#3987e5"
SELL_COLOR = "#d95926"
ALERT = "#e66767"

SANS = "font-family:'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "font-family:Consolas,'SF Mono',Menlo,'Courier New',monospace"
LABEL = f"{SANS};font-size:11px;letter-spacing:1px;text-transform:uppercase;color:{MUTED}"
TABLE = 'role="presentation" cellpadding="0" cellspacing="0" border="0"'
HIDDEN = "display:none;mso-hide:all;"  # shown only where the phone rules below apply

# Phone layout. Inline styles draw the desktop email; these rules override them where
# the reader honours media queries (the Gmail app does, Gmail in a phone's browser may
# not, and then the desktop layout is shown). The header stacks into title, reading
# and rates, and each bank's name moves to a line of its own above its chart.
PHONE_CSS = """@media only screen and (max-width:600px){
.outer{padding:12px 6px!important}
.pad{padding-left:18px!important;padding-right:18px!important}
.stack{display:block!important;width:100%!important;white-space:normal!important}
.title{font-size:28px!important;line-height:32px!important}
.rates{width:100%!important;margin-top:14px!important}
.rate{width:50%!important;text-align:left!important;padding-left:0!important}
.wide{display:none!important}
.phone{display:table-row!important}
.value{border-top:0!important;padding-top:2px!important}
.track{width:auto!important}
.buy{text-align:left!important;padding-left:0!important}
.sell{text-align:right!important;padding-right:0!important}
}"""

# User-facing text, one entry per language. Everything the reader sees lives here.
TEXTS: Mapping[str, Mapping[str, str]] = {
    "es": {
        "decimal": ",",
        "title": "Pizarra del Dólar",
        "reading": "Lectura del {date} (hora de Bolivia), en bolivianos por dólar",
        "official": "Oficial BCB",
        "parallel": "Paralelo",
        "best_deal": "Mejor oferta de hoy",
        "to_buy": "Para comprar dólares",
        "to_buy_detail": "vende a Bs {price}, la venta más baja",
        "to_sell": "Para vender tus dólares",
        "to_sell_detail": "compra a Bs {price}, la compra más alta",
        "average_gap": "Diferencia media entre venta y compra",
        "across_banks": "en {count} bancos",
        "by_bank": "Compra y venta por banco",
        "legend_buy": "Compra (el banco te paga)",
        "legend_sell": "Venta (el banco te cobra)",
        "bank": "Banco",
        "buy": "Compra",
        "sell": "Venta",
        "note": (
            "Las flechas comparan con la lectura anterior. Las líneas verticales marcan el oficial del BCB "
            "y el dólar paralelo (USDT en Binance P2P, punto medio entre compra y venta)."
        ),
        "missing": "Sin datos en esta lectura: {banks}",
        "open_dashboard": "Ver el tablero completo",
        "disclaimer": (
            "Proyecto personal con fines informativos, sin afiliación con los bancos ni con el BCB. "
            "Los datos se toman de sitios públicos y pueden contener errores; no constituyen asesoría financiera."
        ),
        "subscribed": "Recibes este correo porque te suscribiste.",
        "unsubscribe": "Darme de baja",
        "subject": "Dólar Bolivia {date}: venta desde Bs {sell}, compra hasta Bs {buy}",
    },
    "en": {
        "decimal": ".",
        "title": "Dollar Board",
        "reading": "Reading from {date} (Bolivia time), in bolivianos per dollar",
        "official": "BCB official",
        "parallel": "Parallel",
        "best_deal": "Best deal today",
        "to_buy": "To buy dollars",
        "to_buy_detail": "sells at Bs {price}, the lowest sell",
        "to_sell": "To sell your dollars",
        "to_sell_detail": "buys at Bs {price}, the highest buy",
        "average_gap": "Average gap between sell and buy",
        "across_banks": "across {count} banks",
        "by_bank": "Buy and sell by bank",
        "legend_buy": "Buy (the bank pays you)",
        "legend_sell": "Sell (the bank charges you)",
        "bank": "Bank",
        "buy": "Buy",
        "sell": "Sell",
        "note": (
            "Arrows compare with the previous reading. The vertical lines mark the BCB official rate "
            "and the parallel dollar (USDT on Binance P2P, midpoint between buy and sell)."
        ),
        "missing": "No data in this reading: {banks}",
        "open_dashboard": "Open the full dashboard",
        "disclaimer": (
            "Personal project for informational purposes, not affiliated with the banks or the BCB. "
            "Data comes from public websites and may contain errors; it is not financial advice."
        ),
        "subscribed": "You receive this email because you subscribed.",
        "unsubscribe": "Unsubscribe",
        "subject": "Bolivia dollar {date}: sell from Bs {sell}, buy up to Bs {buy}",
    },
}


class Email(NamedTuple):
    subject: str
    html: str
    plain: str


class Scale(NamedTuple):
    """Horizontal Bs scale shared by every row of the chart."""

    low: float
    high: float

    def percent(self, value: float) -> float:
        return (value - self.low) / (self.high - self.low) * 100

    def ticks(self, step: float = 0.5) -> tuple[float, ...]:
        count = round((self.high - self.low) / step)
        return tuple(self.low + i * step for i in range(count + 1))


# --- Pure functions: values and recipients ------------------------------------------


def fmt(value: float | None, text: Mapping[str, str], digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}".replace(".", text["decimal"])


def scale_for(values: Iterable[float | None]) -> Scale:
    present = tuple(v for v in values if v is not None)
    return Scale(math.floor((min(present) - 0.1) * 2) / 2, math.ceil((max(present) + 0.1) * 2) / 2)


def display_name(source: str, text: Mapping[str, str]) -> str:
    return text["parallel"] if source == PARALLEL_SOURCE else source


def addresses_in(text: str | None) -> tuple[str, ...]:
    """Every distinct email address found in a text, lower-cased, in order of appearance."""
    return tuple(dict.fromkeys(match.lower() for match in EMAIL_PATTERN.findall(text or "")))


def is_unsubscribe(cells: Iterable[str]) -> bool:
    return any(cell.strip().lower().startswith(UNSUBSCRIBE_WORDS) for cell in cells)


def subscribers_from_sheet(sheet: str | None) -> tuple[str, ...]:
    """Addresses whose most recent form answer is a subscription.

    Each row of the responses CSV holds an address and, optionally, the chosen
    action. Rows come in the order they were submitted, so a later row overrides
    an earlier one from the same address.
    """
    subscribed: dict[str, bool] = {}
    for cells in csv.reader(io.StringIO(sheet or "")):
        for address in addresses_in(" ".join(cells))[:1]:
            subscribed = {**subscribed, address: not is_unsubscribe(cells)}
    return tuple(address for address, active in subscribed.items() if active)


def recipients_for(always: str | None, sheet: str | None) -> tuple[str, ...]:
    """The fixed recipients followed by the current subscribers, without repeats."""
    return tuple(dict.fromkeys((*addresses_in(always), *subscribers_from_sheet(sheet))))


def describe_sheet(sheet: str | None) -> str:
    """One line about the form responses, without revealing any address."""
    if not sheet:
        return "Form responses: none configured or empty."
    if sheet.lstrip().lower().startswith(("<!doctype", "<html")):
        return (
            "Form responses: SUBSCRIBERS_URL returned a web page, not CSV. "
            "Publish the responses sheet to the web as CSV and store that link."
        )
    rows = tuple(csv.reader(io.StringIO(sheet)))
    with_address = sum(1 for cells in rows if addresses_in(" ".join(cells)))
    return (
        f"Form responses: {len(rows)} rows, {with_address} with an address, "
        f"{len(subscribers_from_sheet(sheet))} currently subscribed."
    )


def is_fresh(reading: Reading, now: datetime, max_age: timedelta = MAX_READING_AGE) -> bool:
    return now - datetime.fromisoformat(reading.timestamp) <= max_age


def blocking_problem(
    reading: Reading,
    recipient_count: int,
    now: datetime,
    max_recipients: int = MAX_RECIPIENTS,
    max_age: timedelta = MAX_READING_AGE,
) -> str | None:
    """Why the email must not go out, or None when it is safe to send."""
    if not is_fresh(reading, now, max_age):
        return f"The latest reading ({reading.timestamp}) is older than {max_age}; not sending stale prices."
    if recipient_count > max_recipients:
        return (
            f"{recipient_count} recipients exceed the limit of {max_recipients}; nothing was sent. "
            "Check the sign-up sheet for abuse, or raise MAIL_MAX_RECIPIENTS."
        )
    return None


def batches(items: Sequence, size: int) -> tuple[tuple, ...]:
    """Split a sequence into consecutive groups of at most `size` items."""
    return tuple(tuple(items[start : start + size]) for start in range(0, len(items), size))


def unsubscribe_link(template: str | None, recipient: str) -> str | None:
    """The pre-filled form link for one recipient, or None when none is configured."""
    return template.replace("{email}", quote(recipient)) if template else None


# --- Pure functions: HTML fragments -------------------------------------------------


def blank(height: int, color: str, extra: str = "") -> str:
    """A solid block; the non-breaking space keeps clients from collapsing it."""
    return f'<div style="{extra}height:{height}px;background:{color};font-size:0;line-height:0">&nbsp;</div>'


def half_dot(color: str, side: str) -> str:
    """Half of a 10px dot. Two halves meet on a cell boundary so the dot is centred on it."""
    radius = "5px 0 0 5px" if side == "left" else "0 5px 5px 0"
    return (
        f'<div style="display:inline-block;vertical-align:middle;width:5px;height:10px;'
        f'border-radius:{radius};background:{color};font-size:0;line-height:0">&nbsp;</div>'
    )


def edge_cell(color: str, side: str, width: str = "") -> str:
    """Track cell that ends (or starts) with half a dot, flush against its neighbour."""
    align = "right" if side == "left" else "left"
    return (
        f'<td align="{align}" valign="middle" style="{width}height:22px;font-size:0;line-height:0">'
        f"{half_dot(color, side)}</td>"
    )


def reference_lines(scale: Scale, references: Sequence[tuple[float | None, str]]) -> str:
    """Background that draws each reference rate as a vertical line across a track."""

    def line(value: float, color: str) -> str:
        at = scale.percent(value)
        return (
            f"linear-gradient(90deg,transparent {at - 0.4:.2f}%,{color} {at - 0.4:.2f}%,"
            f"{color} {at + 0.4:.2f}%,transparent {at + 0.4:.2f}%)"
        )

    lines = ",".join(line(value, color) for value, color in references if value is not None)
    return f"background-image:{lines};" if lines else ""


def track_html(quote: Quote, scale: Scale, lines: str) -> str:
    """One chart row: a buy dot and a sell dot joined by a bar, each centred on its value."""
    has_both = quote.buy is not None and quote.sell is not None
    first_color = BUY_COLOR if quote.buy is not None else SELL_COLOR
    left = scale.percent(quote.buy if quote.buy is not None else quote.sell)
    bar = ""
    if has_both:
        span = max(scale.percent(quote.sell) - left, 0.5)
        bar = (
            f'<td valign="middle" style="width:{span:.2f}%"><table {TABLE} width="100%" style="width:100%"><tr>'
            f'<td width="5" style="width:5px;font-size:0;line-height:0">{half_dot(BUY_COLOR, "right")}</td>'
            f'<td valign="middle">{blank(3, AXIS)}</td>'
            f'<td width="5" style="width:5px;font-size:0;line-height:0">{half_dot(SELL_COLOR, "left")}</td>'
            f"</tr></table></td>"
        )
    return (
        f'<table {TABLE} width="100%" style="width:100%;table-layout:fixed;{lines}"><tr>'
        f'{edge_cell(first_color, "left", f"width:{left:.2f}%;")}{bar}'
        f'{edge_cell(SELL_COLOR if has_both else first_color, "right")}</tr></table>'
    )


def change_html(current: float | None, previous: float | None, text: Mapping[str, str]) -> str:
    if current is None or previous is None or current == previous:
        return ""
    arrow = "▲" if current > previous else "▼"
    return f'<div style="{MONO};font-size:11px;color:{MUTED}">{arrow} {fmt(abs(current - previous), text)}</div>'


def number_cell(value, previous, side: str, align: str, text: Mapping[str, str]) -> str:
    return (
        f'<td class="value {side}" width="62" align="{align}" style="width:62px;padding:10px 8px;'
        f'border-top:1px solid {GRID};{MONO};font-size:14px;color:{INK}">'
        f"{fmt(value, text)}{change_html(value, previous, text)}</td>"
    )


def row_html(bank: str, quote: Quote, previous: Quote, scale: Scale, lines: str, text) -> str:
    """A bank's row. On phones its name is shown by the first row instead of the first cell."""
    name = f"{SANS};font-size:14px;font-weight:600;color:{INK}"
    return (
        f'<tr class="phone" style="{HIDDEN}"><td colspan="4" style="padding:10px 0 0;'
        f'border-top:1px solid {GRID};{name}">{bank}</td></tr>'
        f'<tr><td class="wide" style="padding:10px 0;border-top:1px solid {GRID};{name}">{bank}</td>'
        f'{number_cell(quote.buy, previous.buy, "buy", "right", text)}'
        f'<td class="value track" width="46%" style="width:46%;padding:10px 5px;border-top:1px solid {GRID}">'
        f"{track_html(quote, scale, lines)}</td>"
        f'{number_cell(quote.sell, previous.sell, "sell", "left", text)}</tr>'
    )


def axis_html(scale: Scale, text: Mapping[str, str]) -> str:
    """Tick labels above the tracks; each label starts at its tick."""
    ticks = scale.ticks()
    width = 100 / (len(ticks) - 1)
    cells = "".join(
        f'<td style="width:{width:.2f}%;{MONO};font-size:10px;color:{MUTED}">{fmt(tick, text, 1)}</td>'
        for tick in ticks[:-1]
    )
    return f'<table {TABLE} width="100%" style="width:100%;table-layout:fixed"><tr>{cells}</tr></table>'


def header_row_html(scale: Scale, text: Mapping[str, str]) -> str:
    return (
        f'<tr><td class="wide" style="padding:0 0 8px;{LABEL}">{text["bank"]}</td>'
        f'<td class="buy" align="right" style="padding:0 8px 8px;{LABEL}">{text["buy"]}</td>'
        f'<td style="padding:0 5px 8px">{axis_html(scale, text)}</td>'
        f'<td class="sell" align="left" style="padding:0 8px 8px;{LABEL}">{text["sell"]}</td></tr>'
    )


def metric_html(label: str, value: float | None, color: str, text: Mapping[str, str]) -> str:
    return (
        f'<td class="rate" align="right" valign="bottom" style="padding-left:20px;white-space:nowrap">'
        f'<div style="{LABEL}">{label}</div>'
        f'<div style="{MONO};font-size:28px;line-height:34px;color:{color}">{fmt(value, text)}</div></td>'
    )


def column_html(label: str, headline: str, detail: str, headline_style: str) -> str:
    return (
        f'<td valign="top" style="width:33.33%;padding:0 12px 0 0">'
        f'<div style="{SANS};font-size:13px;line-height:18px;color:{INK_2}">{label}</div>'
        f'<div style="{headline_style};color:{INK};padding:4px 0">{headline}</div>'
        f'<div style="{SANS};font-size:13px;line-height:18px;color:{INK_2}">{detail}</div></td>'
    )


def deal_html(label: str, deal: Deal, detail: str, text: Mapping[str, str]) -> str:
    """A best-deal column: the winning bank is the headline, its price the detail."""
    headline = ", ".join(deal.banks) or "—"
    style = f"{SANS};font-size:20px;line-height:26px;font-weight:700"
    return column_html(label, headline, detail.format(price=fmt(deal.price, text)), style)


def legend_html(text: Mapping[str, str]) -> str:
    def dot_key(color: str, label: str) -> str:
        return f'<span style="color:{color};font-size:14px">●</span>&nbsp;{label}'

    def line_key(color: str, label: str) -> str:
        return f'<span style="color:{color};font-weight:700">|</span>&nbsp;{label}'

    keys = (
        dot_key(BUY_COLOR, text["legend_buy"]),
        dot_key(SELL_COLOR, text["legend_sell"]),
        line_key(ACCENT, text["official"]),
        line_key(PARALLEL_COLOR, text["parallel"]),
    )
    return f'<div style="{SANS};font-size:12px;line-height:20px;color:{INK_2}">{" &nbsp;&nbsp; ".join(keys)}</div>'


def notice_html(missing: Sequence[str], text: Mapping[str, str]) -> str:
    if not missing:
        return ""
    names = ", ".join(display_name(source, text) for source in missing)
    return f'<div style="{SANS};font-size:13px;color:{ALERT};padding-top:10px">{text["missing"].format(banks=names)}</div>'


def button_html(url: str | None, text: Mapping[str, str]) -> str:
    if not url:
        return ""
    return (
        f'<tr><td align="center" style="padding:6px 28px 24px">'
        f'<a href="{url}" style="display:inline-block;padding:11px 22px;border-radius:6px;background:{INK};'
        f'{SANS};font-size:14px;font-weight:700;color:{PAGE};text-decoration:none">{text["open_dashboard"]}</a>'
        f"</td></tr>"
    )


def subscription_html(unsubscribe_url: str | None, text: Mapping[str, str]) -> str:
    link = (
        f' <a href="{unsubscribe_url}" style="color:{ACCENT};font-weight:700;text-decoration:underline">'
        f'{text["unsubscribe"]}</a>'
        if unsubscribe_url
        else ""
    )
    return (
        f'<div style="{SANS};font-size:13px;line-height:19px;color:{INK_2};max-width:600px;padding-top:16px">'
        f'{text["subscribed"]}{link}</div>'
    )


def plain_text(
    latest: Reading,
    sources: Iterable[str],
    text: Mapping[str, str],
    date: str,
    dashboard_url: str | None,
    unsubscribe_url: str | None,
) -> str:
    """The same content as the HTML, for clients and filters that read plain text."""
    banks = priced_banks(latest)
    cheapest, best_paying = best_sell(banks), best_buy(banks)
    missing = missing_sources(latest, sources)
    lines = (
        text["title"],
        text["reading"].format(date=date),
        "",
        f'{text["official"]}: Bs {fmt(official_of(latest), text)}',
        f'{text["parallel"]}: Bs {fmt(parallel_of(latest), text)}',
        "",
        text["best_deal"],
        f'- {text["to_buy"]}: {", ".join(cheapest.banks) or "—"} '
        f'({text["to_buy_detail"].format(price=fmt(cheapest.price, text))})',
        f'- {text["to_sell"]}: {", ".join(best_paying.banks) or "—"} '
        f'({text["to_sell_detail"].format(price=fmt(best_paying.price, text))})',
        "",
        text["by_bank"],
        *(
            f'- {bank}: {text["buy"]} {fmt(q.buy, text)} / {text["sell"]} {fmt(q.sell, text)}'
            for bank, q in banks
        ),
        *(("", text["missing"].format(banks=", ".join(display_name(s, text) for s in missing))) if missing else ()),
        *(("", f'{text["open_dashboard"]}: {dashboard_url}') if dashboard_url else ()),
        "",
        text["disclaimer"],
        text["subscribed"] + (f' {text["unsubscribe"]}: {unsubscribe_url}' if unsubscribe_url else ""),
    )
    return "\n".join(lines) + "\n"


def build(
    readings: Sequence[Reading],
    sources: Iterable[str],
    lang: str = DEFAULT_LANG,
    dashboard_url: str | None = None,
    unsubscribe_url: str | None = None,
) -> Email:
    """Build the email for the latest reading, compared with the previous one."""
    text = TEXTS.get(lang, TEXTS[DEFAULT_LANG])
    latest = readings[-1]
    previous = readings[-2].banks if len(readings) > 1 else {}
    date = datetime.fromisoformat(latest.timestamp).strftime("%d/%m/%Y %H:%M")
    official, parallel = official_of(latest), parallel_of(latest)
    banks = priced_banks(latest)
    cheapest, best_paying = best_sell(banks), best_buy(banks)
    gap, gap_count = average_gap(banks)
    scale = scale_for([official, parallel, *(v for _, q in banks for v in (q.buy, q.sell))])
    lines = reference_lines(scale, ((official, ACCENT), (parallel, PARALLEL_COLOR)))
    rows = "".join(row_html(b, q, previous.get(b, NO_DATA), scale, lines, text) for b, q in banks)
    deals = (
        deal_html(text["to_buy"], cheapest, text["to_buy_detail"], text)
        + deal_html(text["to_sell"], best_paying, text["to_sell_detail"], text)
        + column_html(
            text["average_gap"],
            fmt(gap, text),
            text["across_banks"].format(count=gap_count),
            f"{MONO};font-size:22px;line-height:26px",
        )
    )
    html = f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>{PHONE_CSS}</style></head>
<body style="margin:0;padding:0;background:{PAGE}">
<div style="margin:0;padding:0;background:{PAGE}">
<table {TABLE} width="100%" bgcolor="{PAGE}" style="width:100%;background:{PAGE}"><tr><td class="outer" align="center" style="padding:28px 12px">
<table {TABLE} width="640" style="width:100%;max-width:640px;background:{CARD};border:1px solid {GRID};border-radius:10px">
<tr><td class="pad" style="padding:28px 28px 0">
  <table {TABLE} width="100%" style="width:100%"><tr>
    <td class="stack" valign="bottom">
      <div class="title" style="{SANS};font-size:32px;line-height:36px;font-weight:800;letter-spacing:-0.5px;color:{INK}">{text["title"]}</div>
      <div style="{SANS};font-size:13px;line-height:19px;color:{INK_2};padding-top:6px">{text["reading"].format(date=date)}</div>
    </td>
    <td class="stack" align="right" valign="bottom" style="width:1%;white-space:nowrap">
      <table class="rates" {TABLE}><tr>
        {metric_html(text["official"], official, ACCENT, text)}
        {metric_html(text["parallel"], parallel, PARALLEL_COLOR, text)}
      </tr></table>
    </td>
  </tr></table>
  {blank(2, INK, "margin-top:16px;")}
</td></tr>
<tr><td class="pad" style="padding:24px 28px 0">
  <div style="{SANS};font-size:19px;line-height:24px;font-weight:700;color:{INK};padding-bottom:12px">{text["best_deal"]}</div>
  <table {TABLE} width="100%" style="width:100%;table-layout:fixed"><tr>{deals}</tr></table>
</td></tr>
<tr><td class="pad" style="padding:28px 28px 0">
  <div style="{SANS};font-size:19px;line-height:24px;font-weight:700;color:{INK}">{text["by_bank"]}</div>
  <div style="padding-top:6px">{legend_html(text)}</div>
</td></tr>
<tr><td class="pad" style="padding:16px 28px 0">
  <table {TABLE} width="100%" style="width:100%">
{header_row_html(scale, text)}
{rows}
  </table>
</td></tr>
<tr><td class="pad" style="padding:14px 28px 22px;border-top:1px solid {GRID}">
  <div style="{SANS};font-size:12px;line-height:18px;color:{MUTED}">{text["note"]}</div>
  <div style="{SANS};font-size:12px;line-height:18px;color:{MUTED};padding-top:8px">{text["disclaimer"]}</div>
  {notice_html(missing_sources(latest, sources), text)}
</td></tr>
{button_html(dashboard_url, text)}
</table>
{subscription_html(unsubscribe_url, text)}
</td></tr></table>
</div>
</body></html>"""
    subject = text["subject"].format(date=date, sell=fmt(cheapest.price, text), buy=fmt(best_paying.price, text))
    return Email(subject, html, plain_text(latest, sources, text, date, dashboard_url, unsubscribe_url))


def to_message(email: Email, sender: str, recipient: str, unsubscribe_url: str | None = None) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = email.subject
    message["From"] = sender
    message["To"] = recipient
    if unsubscribe_url:
        message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    message.set_content(email.plain)
    message.add_alternative(email.html, subtype="html")
    return message


# --- Effects: disk, environment and network --------------------------------------


def fetch_sheet(url: str | None) -> str:
    """Download the form responses, or return nothing when no URL is configured."""
    if not url:
        return ""
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.content.decode("utf-8", errors="replace")


Sender = Callable[[Sequence[EmailMessage]], tuple[int, int]]  # batch -> (delivered, refused)


def smtp_sender(user: str, password: str) -> Sender:
    """Sender that logs in to Gmail's SMTP server with an app password."""

    def send(batch: Sequence[EmailMessage]) -> tuple[int, int]:
        delivered = refused = 0
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(user, password)
            for message in batch:
                try:
                    smtp.send_message(message)
                    delivered += 1
                except smtplib.SMTPRecipientsRefused:  # one bad address must not stop the rest
                    refused += 1
        return delivered, refused

    return send


def api_sender(client_id: str, client_secret: str, refresh_token: str) -> Sender:
    """Sender that uses the Gmail API with a send-only credential."""

    def send(batch: Sequence[EmailMessage]) -> tuple[int, int]:
        return gmail_api.send_batch(batch, gmail_api.fetch_access_token(client_id, client_secret, refresh_token))

    return send


def sender_from(env: Mapping[str, str]) -> Sender:
    """Prefer the send-only API credential; fall back to the app password."""
    if env.get("GMAIL_REFRESH_TOKEN"):
        return api_sender(env["GMAIL_CLIENT_ID"], env["GMAIL_CLIENT_SECRET"], env["GMAIL_REFRESH_TOKEN"])
    return smtp_sender(env["GMAIL_USER"], env["GMAIL_APP_PASSWORD"])


def send_all(
    messages: Sequence[EmailMessage],
    send: Sender,
    batch_size: int = BATCH_SIZE,
    pause_seconds: float = BATCH_PAUSE_SECONDS,
    pause=time.sleep,
) -> tuple[int, int]:
    """Send the messages in batches, pausing between them. Returns (delivered, refused)."""
    delivered = refused = 0
    for index, batch in enumerate(batches(messages, batch_size)):
        if index:
            pause(pause_seconds)
        sent, rejected = send(batch)
        delivered, refused = delivered + sent, refused + rejected
    return delivered, refused


def main() -> None:
    env = os.environ
    readings = read_readings()
    lang, dashboard_url = env.get("MAIL_LANG") or DEFAULT_LANG, env.get("DASHBOARD_URL")
    if "--preview" in sys.argv:
        link = unsubscribe_link(env.get("UNSUBSCRIBE_URL"), "reader@example.com")
        email = build(readings, SOURCES, lang, dashboard_url, link)
        Path("email_preview.html").write_text(email.html, encoding="utf-8")
        print(email.subject)
        return
    user = env["GMAIL_USER"]
    only_to = addresses_in(env.get("MAIL_ONLY_TO"))
    sheet = "" if only_to else fetch_sheet(env.get("SUBSCRIBERS_URL"))
    recipients = only_to or recipients_for(env.get("MAIL_TO"), sheet) or (user,)
    print("Test send: subscribers ignored." if only_to else describe_sheet(sheet))
    # A test send to chosen addresses may reuse an old reading; a real send may not.
    max_age = timedelta.max if only_to else MAX_READING_AGE
    max_recipients = int(env.get("MAIL_MAX_RECIPIENTS") or MAX_RECIPIENTS)
    problem = blocking_problem(readings[-1], len(recipients), datetime.now(timezone.utc), max_recipients, max_age)
    if "--check" in sys.argv:
        print(f"{len(recipients)} recipient(s) would receive the email; nothing was sent.")
        print(f"A real send would be blocked: {problem}" if problem else "A real send would go ahead.")
        return
    if problem:
        sys.exit(problem)
    links = tuple(unsubscribe_link(env.get("UNSUBSCRIBE_URL"), recipient) for recipient in recipients)
    messages = tuple(
        to_message(build(readings, SOURCES, lang, dashboard_url, link), user, recipient, link)
        for recipient, link in zip(recipients, links)
    )
    delivered, refused = send_all(messages, sender_from(env))
    print(f"Email sent to {delivered} recipient(s); {refused} refused")


if __name__ == "__main__":
    main()
