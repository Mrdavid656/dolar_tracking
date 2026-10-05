# dolar_market

Reads the dollar exchange rate published by the BCB and 11 Bolivian banks twice a day
(08:00 and 20:00, Bolivia time), stores it in `data/rates.csv` and emails a summary.

## Conventions

- Code, comments, identifiers, file names, commit messages and docs are written in English.
- Text shown to the reader (dashboard, email) is bilingual: Spanish and English.
  Every user-facing string lives in a translation table (`TEXTS` in
  `dashboard_template.html` and in `mailer.py`); add both languages when adding a string.

## Local usage

```
pip install -r requirements.txt
python -m dolar_market.scrape             # append one reading to the CSV
python -m dolar_market.mailer --preview   # write email_preview.html without sending
python -m dolar_market.dashboard          # generate dashboard.html from the CSV
```

## Dataset

`data/rates.csv` holds one row per bank and reading, in bolivianos per dollar:

| column | content |
|---|---|
| `timestamp` | moment of the reading, ISO 8601 with the -04:00 offset |
| `bank` | name of the source |
| `buy` | what the bank pays for one dollar (empty if not published) |
| `sell` | what the bank charges for one dollar |
| `official` | official exchange rate shown on that site |

## Automation with GitHub Actions

`.github/workflows/rates.yml` runs at 12:00 and 00:00 UTC, commits the CSV and sends the
email only with the morning reading. To enable it:

1. Push this repository to GitHub.
2. Create a Gmail app password (requires 2-step verification):
   https://myaccount.google.com/apppasswords
3. Under *Settings → Secrets and variables → Actions* add the secrets:
   - `GMAIL_USER`: your Gmail address
   - `GMAIL_APP_PASSWORD`: the app password
   - `MAIL_TO` (optional): comma-separated recipients; defaults to `GMAIL_USER`
4. Optionally add the repository variable `MAIL_LANG` (`es` or `en`; defaults to `es`)
   to choose the email language.
5. Trigger the workflow manually from the *Actions* tab to test it.

## Dashboard

`python -m dolar_market.dashboard` embeds every reading into `dashboard_template.html`
and writes a self-contained `dashboard.html`. The page has an ES/EN toggle that
remembers the viewer's choice.

## Code structure

Pure functions (they transform data and touch nothing external) are kept apart from
effects (network, disk, clock, email), which sit at the edges of each module.

| module | content |
|---|---|
| `models.py` | immutable types: `Quote`, `Row`, `Reading` |
| `sources.py` | `SOURCES`: each bank as a function built with `from_html` or `from_json` |
| `storage.py` | read and write the CSV; group rows into readings |
| `scrape.py` | query the sources, validate and save |
| `mailer.py` | build the summary HTML and send it |
| `dashboard.py` | embed the readings into `dashboard_template.html` |

## Adding or fixing a source

Each bank is one entry of `SOURCES` in `dolar_market/sources.py`: a URL plus the patterns
to search for (`from_html`) or a function that reads the JSON (`from_json`).
If a site changes, only that source fails: the scraper reports it as `FAIL`
and the email lists it as having no data.
