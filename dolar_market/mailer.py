"""Send a Gmail summary of the latest reading in data/rates.csv.

Usage:
    python -m dolar_market.mailer            # send the email
    python -m dolar_market.mailer --preview  # only write email_preview.html

Environment variables: GMAIL_USER, GMAIL_APP_PASSWORD, MAIL_TO (optional,
defaults to GMAIL_USER; accepts several comma-separated recipients) and
MAIL_LANG (optional, "es" or "en"; defaults to "es").

The HTML mirrors the dashboard's dark board. Email clients run no scripts and
ignore most CSS, so the layout is built from tables with inline styles and the
chart from table cells sized in percentages.
"""

import math
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

NO_DATA = Quote()
DEFAULT_LANG = "es"

# The dashboard's dark palette.
PAGE = "#0d0f0e"
CARD = "#181a19"
INK = "#f4f6f3"
INK_2 = "#c0c5bf"
MUTED = "#898f89"
GRID = "#2a2d2b"
AXIS = "#3a3e3b"
ACCENT = "#6fcfb4"
BUY_COLOR = "#3987e5"
SELL_COLOR = "#d95926"
ALERT = "#e66767"

SANS = "font-family:'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "font-family:Consolas,'SF Mono',Menlo,'Courier New',monospace"
LABEL = f"{SANS};font-size:11px;letter-spacing:1px;text-transform:uppercase;color:{MUTED}"
TABLE = 'role="presentation" cellpadding="0" cellspacing="0" border="0"'

# User-facing text, one entry per language. Everything the reader sees lives here.
TEXTS: Mapping[str, Mapping[str, str]] = {
    "es": {
        "decimal": ",",
        "title": "Pizarra del Dólar",
        "reading": "Lectura del {date} (hora de Bolivia), en bolivianos por dólar",
        "official": "Oficial BCB",
        "cheapest_sell": "Dónde comprar dólares más barato",
        "best_buy": "Dónde pagan más por tus dólares",
        "average_gap": "Diferencia media entre venta y compra",
        "across_banks": "en {count} bancos",
        "by_bank": "Compra y venta por banco",
        "legend_buy": "Compra (el banco te paga)",
        "legend_sell": "Venta (el banco te cobra)",
        "bank": "Banco",
        "buy": "Compra",
        "sell": "Venta",
        "note": "Las flechas comparan con la lectura anterior. La línea vertical marca el oficial del BCB.",
        "missing": "Sin datos en esta lectura: {banks}",
        "subject": "Dólar Bolivia {date}: venta desde Bs {sell}, compra hasta Bs {buy}",
        "plain": "Tu cliente de correo no muestra HTML.",
    },
    "en": {
        "decimal": ".",
        "title": "Dollar Board",
        "reading": "Reading from {date} (Bolivia time), in bolivianos per dollar",
        "official": "BCB official",
        "cheapest_sell": "Cheapest place to buy dollars",
        "best_buy": "Best price for selling your dollars",
        "average_gap": "Average gap between sell and buy",
        "across_banks": "across {count} banks",
        "by_bank": "Buy and sell by bank",
        "legend_buy": "Buy (the bank pays you)",
        "legend_sell": "Sell (the bank charges you)",
        "bank": "Bank",
        "buy": "Buy",
        "sell": "Sell",
        "note": "Arrows compare with the previous reading. The vertical line marks the BCB official rate.",
        "missing": "No data in this reading: {banks}",
        "subject": "Bolivia dollar {date}: sell from Bs {sell}, buy up to Bs {buy}",
        "plain": "Your email client does not display HTML.",
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


# --- Pure functions: numbers about a reading ---------------------------------------


def fmt(value: float | None, text: Mapping[str, str], digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}".replace(".", text["decimal"])


def official_of(reading: Reading) -> float | None:
    return next((q.official for q in reading.banks.values() if q.official is not None), None)


def priced_banks(reading: Reading) -> tuple[tuple[str, Quote], ...]:
    """Banks that publish buy or sell, ordered like the dashboard: cheapest seller first."""
    banks = ((b, q) for b, q in reading.banks.items() if q.buy is not None or q.sell is not None)
    return tuple(sorted(banks, key=lambda p: (p[1].sell is None, p[1].sell or 0, -(p[1].buy or 0), p[0])))


def missing_banks(reading: Reading, sources: Iterable[str]) -> tuple[str, ...]:
    return tuple(bank for bank in sources if bank not in reading.banks)


def banks_with(banks: Sequence[tuple[str, Quote]], field: str, value: float | None) -> str:
    return ", ".join(bank for bank, q in banks if value is not None and getattr(q, field) == value)


def average_gap(banks: Sequence[tuple[str, Quote]]) -> tuple[float | None, int]:
    """Mean of sell minus buy, and how many banks publish both values."""
    gaps = tuple(q.sell - q.buy for _, q in banks if q.buy is not None and q.sell is not None)
    return (sum(gaps) / len(gaps) if gaps else None), len(gaps)


def scale_for(values: Iterable[float | None]) -> Scale:
    present = tuple(v for v in values if v is not None)
    return Scale(math.floor((min(present) - 0.1) * 2) / 2, math.ceil((max(present) + 0.1) * 2) / 2)


# --- Pure functions: HTML fragments -------------------------------------------------


def blank(height: int, color: str) -> str:
    """A solid block; the non-breaking space keeps clients from collapsing it."""
    return f'<div style="height:{height}px;background:{color};font-size:0;line-height:0">&nbsp;</div>'


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


def official_line(scale: Scale, official: float | None) -> str:
    """Background that draws the official rate as a vertical line across a track."""
    if official is None:
        return ""
    at = scale.percent(official)
    stops = f"transparent {at - 0.4:.2f}%,{ACCENT} {at - 0.4:.2f}%,{ACCENT} {at + 0.4:.2f}%,transparent {at + 0.4:.2f}%"
    return f"background-image:linear-gradient(90deg,{stops});"


def track_html(quote: Quote, scale: Scale, official: float | None) -> str:
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
        f'<table {TABLE} width="100%" style="width:100%;table-layout:fixed;{official_line(scale, official)}"><tr>'
        f'{edge_cell(first_color, "left", f"width:{left:.2f}%;")}{bar}'
        f'{edge_cell(SELL_COLOR if has_both else first_color, "right")}</tr></table>'
    )


def change_html(current: float | None, previous: float | None, text: Mapping[str, str]) -> str:
    if current is None or previous is None or current == previous:
        return ""
    arrow = "▲" if current > previous else "▼"
    return f'<div style="{MONO};font-size:11px;color:{MUTED}">{arrow} {fmt(abs(current - previous), text)}</div>'


def number_cell(value, previous, align: str, text: Mapping[str, str]) -> str:
    return (
        f'<td width="62" align="{align}" style="width:62px;padding:10px 8px;border-top:1px solid {GRID};'
        f'{MONO};font-size:14px;color:{INK}">{fmt(value, text)}{change_html(value, previous, text)}</td>'
    )


def row_html(bank: str, quote: Quote, previous: Quote, scale: Scale, official, text) -> str:
    return (
        f'<tr><td style="padding:10px 0;border-top:1px solid {GRID};{SANS};font-size:14px;font-weight:600;'
        f'color:{INK}">{bank}</td>'
        f'{number_cell(quote.buy, previous.buy, "right", text)}'
        f'<td width="46%" style="width:46%;padding:10px 5px;border-top:1px solid {GRID}">'
        f"{track_html(quote, scale, official)}</td>"
        f'{number_cell(quote.sell, previous.sell, "left", text)}</tr>'
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
        f'<tr><td style="padding:0 0 8px;{LABEL}">{text["bank"]}</td>'
        f'<td align="right" style="padding:0 8px 8px;{LABEL}">{text["buy"]}</td>'
        f'<td style="padding:0 5px 8px">{axis_html(scale, text)}</td>'
        f'<td align="left" style="padding:0 8px 8px;{LABEL}">{text["sell"]}</td></tr>'
    )


def fact_html(label: str, value: float | None, detail: str, text: Mapping[str, str]) -> str:
    return (
        f'<td valign="top" style="width:33.33%;padding:0 12px 0 0">'
        f'<div style="{SANS};font-size:13px;line-height:18px;color:{INK_2}">{label}</div>'
        f'<div style="{MONO};font-size:24px;line-height:34px;color:{INK}">{fmt(value, text)}</div>'
        f'<div style="{SANS};font-size:13px;line-height:18px;color:{INK_2}">{detail}</div></td>'
    )


def legend_html(text: Mapping[str, str]) -> str:
    def key(color: str, label: str) -> str:
        return f'<span style="color:{color};font-size:14px">●</span>&nbsp;{label}'

    return (
        f'<div style="{SANS};font-size:12px;line-height:20px;color:{INK_2}">'
        f'{key(BUY_COLOR, text["legend_buy"])} &nbsp;&nbsp; {key(SELL_COLOR, text["legend_sell"])} &nbsp;&nbsp; '
        f'<span style="color:{ACCENT}">|</span>&nbsp;{text["official"]}</div>'
    )


def notice_html(missing: Sequence[str], text: Mapping[str, str]) -> str:
    if not missing:
        return ""
    message = text["missing"].format(banks=", ".join(missing))
    return f'<div style="{SANS};font-size:13px;color:{ALERT};padding-top:10px">{message}</div>'


def build(readings: Sequence[Reading], sources: Iterable[str], lang: str = DEFAULT_LANG) -> Email:
    """Build the email for the latest reading, compared with the previous one."""
    text = TEXTS.get(lang, TEXTS[DEFAULT_LANG])
    latest = readings[-1]
    previous = readings[-2].banks if len(readings) > 1 else {}
    date = datetime.fromisoformat(latest.timestamp).strftime("%d/%m/%Y %H:%M")
    official = official_of(latest)
    banks = priced_banks(latest)
    min_sell = min((q.sell for _, q in banks if q.sell is not None), default=None)
    max_buy = max((q.buy for _, q in banks if q.buy is not None), default=None)
    gap, gap_count = average_gap(banks)
    scale = scale_for([official, *(v for _, q in banks for v in (q.buy, q.sell))])
    rows = "".join(row_html(b, q, previous.get(b, NO_DATA), scale, official, text) for b, q in banks)
    facts = (
        fact_html(text["cheapest_sell"], min_sell, banks_with(banks, "sell", min_sell), text)
        + fact_html(text["best_buy"], max_buy, banks_with(banks, "buy", max_buy), text)
        + fact_html(text["average_gap"], gap, text["across_banks"].format(count=gap_count), text)
    )
    html = f"""<div style="margin:0;padding:0;background:{PAGE}">
<table {TABLE} width="100%" bgcolor="{PAGE}" style="width:100%;background:{PAGE}"><tr><td align="center" style="padding:28px 12px">
<table {TABLE} width="640" style="width:100%;max-width:640px;background:{CARD};border:1px solid {GRID};border-radius:10px">
<tr><td style="padding:28px 28px 0">
  <table {TABLE} width="100%" style="width:100%"><tr>
    <td valign="bottom">
      <div style="{SANS};font-size:34px;line-height:38px;font-weight:800;letter-spacing:-0.5px;color:{INK}">{text["title"]}</div>
      <div style="{SANS};font-size:13px;line-height:19px;color:{INK_2};padding-top:6px">{text["reading"].format(date=date)}</div>
    </td>
    <td valign="bottom" align="right" style="padding-left:16px;white-space:nowrap">
      <div style="{LABEL}">{text["official"]}</div>
      <div style="{MONO};font-size:32px;line-height:36px;color:{ACCENT}">{fmt(official, text)}</div>
    </td>
  </tr></table>
  {blank(2, INK).replace('<div style="', '<div style="margin-top:16px;')}
</td></tr>
<tr><td style="padding:24px 28px 0">
  <table {TABLE} width="100%" style="width:100%;table-layout:fixed"><tr>{facts}</tr></table>
</td></tr>
<tr><td style="padding:28px 28px 0">
  <div style="{SANS};font-size:19px;line-height:24px;font-weight:700;color:{INK}">{text["by_bank"]}</div>
  <div style="padding-top:6px">{legend_html(text)}</div>
</td></tr>
<tr><td style="padding:16px 28px 0">
  <table {TABLE} width="100%" style="width:100%">
{header_row_html(scale, text)}
{rows}
  </table>
</td></tr>
<tr><td style="padding:14px 28px 26px;border-top:1px solid {GRID}">
  <div style="{SANS};font-size:12px;line-height:18px;color:{MUTED}">{text["note"]}</div>
  {notice_html(missing_banks(latest, sources), text)}
</td></tr>
</table>
</td></tr></table>
</div>"""
    subject = text["subject"].format(date=date, sell=fmt(min_sell, text), buy=fmt(max_buy, text))
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
