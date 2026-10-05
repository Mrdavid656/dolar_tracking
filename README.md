# dolar_market

Tracks the dollar exchange rate published by the BCB, 11 Bolivian banks and the parallel
market. Three times a day it stores a reading in `data/rates.csv` and republishes a
dashboard; once a day it emails a summary to every subscriber.

- Dashboard: https://mrdavid656.github.io/dolar_tracking/
- Readings: 07:00, 13:00 and 19:00 Bolivia time
- Email: 08:00 Bolivia time. [Subscribe or unsubscribe](https://docs.google.com/forms/d/e/1FAIpQLScOe99KN0www_aZeMoC_0ybw3MhPYlrhZhig9BZoGAecjbihg/viewform)

## Conventions

- Code, comments, identifiers, file names, commit messages and docs are written in English.
- Text shown to the reader (dashboard, email) is bilingual: Spanish and English.
  Every user-facing string lives in a translation table (`TEXTS` in
  `dashboard_template.html` and in `mailer.py`); add both languages when adding a string.
- "Buy" is what a bank pays for a dollar and "sell" what it charges. The best deal is
  therefore the **highest** buy and the **lowest** sell.

## Local usage

```
pip install -r requirements-dev.txt
python -m dolar_market.scrape             # append one reading to the CSV
python -m dolar_market.mailer --preview   # write email_preview.html without sending
python -m dolar_market.dashboard          # generate dashboard.html and site/index.html
python -m dolar_market.backfill           # add the sources missing from the latest reading
python -m pytest                          # run the tests
```

## Dataset

`data/rates.csv` holds one row per source and reading, in bolivianos per dollar:

| column | content |
|---|---|
| `timestamp` | moment of the reading, ISO 8601 with the -04:00 offset |
| `bank` | name of the source |
| `buy` | what the bank pays for one dollar (empty if not published) |
| `sell` | what the bank charges for one dollar |
| `official` | official exchange rate shown on that site |

Two sources are references rather than banks: `BCB` (the official rate) and `Parallel`
(USDT/BOB on Binance P2P, as aggregated by CriptoYa). The dashboard and the email show
them as reference lines; the parallel rate displayed is the midpoint of its buy and sell.

## Automation with GitHub Actions

| workflow | when | what |
|---|---|---|
| `rates.yml` | 07:00, 13:00, 19:00 Bolivia time, and on pushes that change data or code | take a reading, commit it, report failing sources, publish the dashboard to GitHub Pages |
| `email.yml` | 08:00 Bolivia time | email the latest reading to the subscribers |
| `tests.yml` | pushes and pull requests | run the test suite |

Settings, under *Settings → Secrets and variables → Actions*:

| name | kind | purpose |
|---|---|---|
| `GMAIL_USER` | secret | Gmail address that sends the email |
| `GMAIL_APP_PASSWORD` | secret | its app password (https://myaccount.google.com/apppasswords) |
| `MAIL_TO` | secret, optional | comma-separated recipients who always get the email |
| `SUBSCRIBERS_URL` | secret, optional | published CSV with the sign-up form's responses |
| `UNSUBSCRIBE_URL` | variable, optional | form link pre-filled to unsubscribe, with `{email}` as placeholder |
| `MAIL_LANG` | variable, optional | email language, `es` (default) or `en` |
| `SUBSCRIBE_URL` | variable, optional | sign-up form linked from the dashboard |

### Subscribers

People subscribe and unsubscribe on their own through one Google Form; nobody maintains
the list by hand. Every morning the workflow reads the form's responses in order and the
most recent answer of each address decides whether it is subscribed. A new subscriber
starts receiving the email at the next 08:00. Each recipient gets an individual message
with a personal "unsubscribe" link that opens the form already filled in.

One-time setup:

1. Create a Google Form with two required questions:
   - a short-answer question for the email address (turn on response validation: *Text → Email*);
   - a multiple-choice question with the options `Suscribirme` and `Darme de baja`.
     An answer starting with "unsubscribe", "cancel", "baja", "darme de baja", "desuscri"
     or "dejar de" removes the address; anything else subscribes it.
2. In the *Responses* tab choose *Link to Sheets*.
3. In that sheet choose *File → Share → Publish to web*, pick the responses tab and the
   *CSV* format, and publish. Store the resulting link in the secret `SUBSCRIBERS_URL`.
   Keep it secret: anyone holding that link can read the subscribers' addresses.
4. In the form choose *⋮ → Get pre-filled link*, type `EMAIL` as the address, select
   `Darme de baja` and copy the link. Replace `EMAIL` with `{email}` and store the result
   in the variable `UNSUBSCRIBE_URL`.
5. Store the form's normal link in the variable `SUBSCRIBE_URL`; the dashboard then shows
   a link to it.

The form only ever appends rows. To keep the sheet to at most one row per address, paste
`scripts/clean_subscribers.gs` into the sheet (*Extensions → Apps Script*) and run
`installTriggers` once. On every submission it deletes the rows an address has superseded,
and it deletes an unsubscription row three days after it was sent. This never changes who
receives the email.

Addresses listed in `MAIL_TO` always receive the email, whatever the form says. Nothing
verifies that the person filling in the form owns the address, so anyone could subscribe
or unsubscribe someone else; to prevent that, turn on *Collect email addresses → Verified*
in the form's settings, which makes respondents sign in with Google.

### Failing sources

When a source is missing from the last three readings, `rates.yml` opens an issue labelled
`source-down`, and closes it once the source answers again.

## Backfill from a local computer

Some sites refuse connections from GitHub's servers. `scripts/register_backfill_task.ps1`
registers a Windows scheduled task that, shortly after each reading, queries from your
computer only the sources that reading lacks and pushes them with the reading's timestamp.
It does nothing when the reading is complete, and skips readings older than three hours.

```
.\scripts\register_backfill_task.ps1
Unregister-ScheduledTask -TaskName DolarTrackingBackfill   # to remove it
```

## Code structure

Pure functions (they transform data and touch nothing external) are kept apart from
effects (network, disk, clock, email), which sit at the edges of each module.

| module | content |
|---|---|
| `models.py` | immutable types: `Quote`, `Row`, `Reading` |
| `sources.py` | `SOURCES`: each source as a URL plus a pure parser (`from_html`, `from_json`) |
| `storage.py` | read and write the CSV; group rows into readings |
| `analysis.py` | questions about readings: references, best deals, failing sources |
| `scrape.py` | query the sources, validate and save |
| `backfill.py` | query only the sources the latest reading lacks |
| `monitor.py` | list the sources that keep failing |
| `mailer.py` | build the summary HTML and send it |
| `dashboard.py` | embed the readings into `dashboard_template.html` |

## Adding or fixing a source

Each source is one entry of `SOURCES` in `dolar_market/sources.py`: a URL plus the patterns
to search for (`from_html`) or a function that reads the JSON (`from_json`). After changing
one, refresh its saved response and expected values, then run the tests:

```
python -m tests.capture_fixtures "Banco Unión"
python -m pytest
```
