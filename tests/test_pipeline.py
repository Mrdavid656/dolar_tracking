"""Storage, scraping, backfill, email and dashboard building."""

from datetime import datetime, timedelta

from dolar_market import dashboard, mailer
from dolar_market.backfill import is_recent
from dolar_market.models import Quote, Reading, Row
from dolar_market.scrape import BOLIVIA, Result, problem, query, report_line, to_rows
from dolar_market.storage import append_rows, group_readings, read_readings, to_record, to_row

ROWS = (
    Row("2026-10-05T13:00:00-04:00", "Alpha", Quote(11.5, 12.3, 12.0)),
    Row("2026-10-05T07:00:00-04:00", "Alpha", Quote(11.4, 12.3, 12.0)),
    Row("2026-10-05T07:00:00-04:00", "Beta", Quote(None, 12.1, None)),
)
READINGS = group_readings(ROWS)


# --- storage ---


def test_record_round_trip_keeps_missing_values():
    record = {key: "" if value is None else str(value) for key, value in to_record(ROWS[2]).items()}
    assert to_row(record) == ROWS[2]


def test_group_readings_is_chronological():
    assert [r.timestamp for r in READINGS] == ["2026-10-05T07:00:00-04:00", "2026-10-05T13:00:00-04:00"]
    assert set(READINGS[0].banks) == {"Alpha", "Beta"}


def test_append_then_read(tmp_path):
    path = tmp_path / "data" / "rates.csv"
    append_rows(ROWS[:1], path)
    append_rows(ROWS[1:], path)
    assert read_readings(path) == READINGS
    assert path.read_text(encoding="utf-8").count("timestamp") == 1


# --- scrape ---


def test_problem_detects_empty_and_implausible_quotes():
    assert problem(Quote(11.5, 12.3, 12.0)) is None
    assert "no value" in problem(Quote())
    assert "out of range" in problem(Quote(buy=1150.0))


def test_query_retries_until_a_source_answers():
    answers = iter([RuntimeError("down"), Quote(sell=12.0)])

    def flaky():
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert query("Alpha", flaky, attempts=2) == Result("Alpha", Quote(sell=12.0))


def test_query_reports_the_error_when_attempts_run_out():
    def broken():
        raise RuntimeError("down")

    result = query("Alpha", broken, attempts=2)
    assert result.quote is None
    assert result.error == "RuntimeError: down"
    assert report_line(result).startswith("FAIL")


def test_to_rows_skips_failures():
    results = (Result("Alpha", Quote(sell=12.0)), Result("Beta", error="boom"))
    assert to_rows("t", results) == (Row("t", "Alpha", Quote(sell=12.0)),)


# --- backfill ---


def test_is_recent():
    now = datetime(2026, 10, 5, 9, 0, tzinfo=BOLIVIA)
    assert is_recent(Reading("2026-10-05T07:00:00-04:00", {}), now)
    assert not is_recent(Reading("2026-10-05T07:00:00-04:00", {}), now + timedelta(hours=2))


# --- mailer ---


def test_email_names_the_best_deals_in_both_languages():
    spanish = mailer.build(READINGS, ["Alpha", "Beta", "Gamma"], "es")
    english = mailer.build(READINGS, ["Alpha", "Beta", "Gamma"], "en", "https://example.com/board")
    assert "Mejor oferta de hoy" in spanish.html and "12,30" in spanish.html
    assert "Best deal today" in english.html and "12.30" in english.html
    assert "https://example.com/board" in english.html
    assert "No data in this reading: Beta, Gamma" in english.html
    assert "▲ 0.10" in english.html  # Alpha's buy rose from 11.4 to 11.5


SHEET = (
    "Timestamp,Email,Action\n"
    "2026-10-05 08:00,Ana@Example.com,Suscribirme\n"
    "2026-10-05 09:00,luis@example.org,Subscribe\n"
    "2026-10-06 10:00,ana@example.com,Darme de baja\n"
    "2026-10-06 11:00,not an address,Subscribe\n"
    "2026-10-07 12:00,eva@example.com,Unsubscribe\n"
    "2026-10-08 13:00,eva@example.com,Suscribirme\n"
)


def test_an_address_that_subscribes_many_times_is_listed_once():
    sheet = "t,Ana@Example.com,Suscribirme\nt, ana@example.com ,Suscribirme\nt,ANA@EXAMPLE.COM,Suscribirme\n"
    assert mailer.subscribers_from_sheet(sheet) == ("ana@example.com",)
    assert mailer.recipients_for("ana@example.com", sheet) == ("ana@example.com",)


def test_describe_sheet_counts_without_revealing_addresses():
    summary = mailer.describe_sheet(SHEET)
    assert summary == "Form responses: 7 rows, 5 with an address, 2 currently subscribed."
    assert "@" not in summary
    assert "not CSV" in mailer.describe_sheet("<!DOCTYPE html><html>Sign in</html>")


def test_last_form_answer_decides_the_subscription():
    assert mailer.subscribers_from_sheet(SHEET) == ("luis@example.org", "eva@example.com")
    assert mailer.subscribers_from_sheet(None) == ()


def test_recipients_join_fixed_addresses_and_subscribers_without_repeats():
    assert mailer.recipients_for("Owner@example.com, luis@example.org", SHEET) == (
        "owner@example.com",
        "luis@example.org",
        "eva@example.com",
    )


def test_each_message_carries_a_personal_unsubscribe_link():
    link = mailer.unsubscribe_link("https://forms.example/f?email={email}&do=Unsubscribe", "ana+x@example.com")
    assert link == "https://forms.example/f?email=ana%2Bx%40example.com&do=Unsubscribe"
    email = mailer.build(READINGS, ["Alpha"], "en", unsubscribe_url=link)
    message = mailer.to_message(email, "me@example.com", "ana+x@example.com", link)
    assert link in email.html and ">Unsubscribe</a>" in email.html
    assert message["To"] == "ana+x@example.com"
    assert message["List-Unsubscribe"] == f"<{link}>"
    assert mailer.unsubscribe_link(None, "ana@example.com") is None


# --- dashboard ---


def test_embed_cannot_close_the_script_tag():
    page = dashboard.embed("<script>const DATA = /*DATA*/;</script>", {"x": "</script>"})
    assert page.count("</script>") == 1


def test_payload_and_document():
    payload = dashboard.to_payload(READINGS, ["Alpha"], "https://example.com/form")
    assert payload["subscribeUrl"] == "https://example.com/form"
    assert payload["readings"][0]["banks"]["Beta"] == {"buy": None, "sell": 12.1, "official": None}
    assert dashboard.to_document("<p>hi</p>").startswith("<!doctype html>")
