# Chennai Gold & Silver Rate Reporter

Fetches Chennai gold and silver rates from goodreturns.in, validates them, saves a JSON file
and a plain-text report, and posts the report to a Telegram **group** through the official
Bot API (`sendMessage`, plain text).

```
https://www.goodreturns.in/gold-rates/chennai.html
https://www.goodreturns.in/silver-rates/chennai.html
```

## How the data is loaded (page inspection)

Both pages are **server-rendered HTML**: prices, the per-weight tables and the 10-day history
are present in the first response, so `requests` + `BeautifulSoup` is enough. Playwright is
**not** used or required. Tables are found by their header signature (for example
`Gram | 24K | 22K | 18K`), not by CSS class names, so cosmetic redesigns are less likely to break
the parser. If the site ever starts serving a JavaScript/bot-check page, the run fails with a
clear message and a saved diagnostic copy of the HTML (it never sends guessed prices).

Extracted fields:

| Gold | Silver |
|---|---|
| City, page date, page title, headline sentence | City, page date, page title, headline sentence |
| 24K / 22K / 18K price per gram, purity, change | Price per gram and per kg, previous-day price, change |
| Price and change for 1, 8, 10, 100 g | Price, previous-day price and change for 1, 8, 10, 100, 1000 g |
| Last 10 days (24K, 22K, with change) | Last 10 days (10 g, 100 g, 1 kg; change on the 1 kg column) |
| Disclaimer note | Monthly high/low/trend summary tables (JSON only) |

The pages show a date but no time of day. The JSON also records `page_meta_timestamp_epoch`
(the number after `#` in the page's `og:url` meta tag, which equals midnight IST of the page
date). Fields the page does not provide are `null` in JSON and `N/A` in the report.

## Project structure

```
main.py                     entry point (python main.py)
goldsilver/
  config.py                 environment-variable settings + validation
  fetcher.py                requests session, timeouts, retries
  parsers.py                gold and silver HTML parsers
  models.py                 data classes
  validation.py             sanity checks (freshness, price ordering, consistency)
  report.py                 plain-text report + Telegram-safe message splitting
  telegram_client.py        Bot API client (retries, error explanations)
  storage.py                JSON / text / diagnostics output
  logging_setup.py          console + rotating file logs, token redaction
  cli.py                    argument parsing and orchestration
tests/                      pytest suite (+ HTML fixtures)
.env.example  .gitignore  requirements.txt  requirements-dev.txt  pytest.ini
```

## Install (Windows, Command Prompt)

Requires Python 3.9 or newer (check with `py -3 --version`).

```bat
cd path\to\gold-silver-telegram
py -3 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Configure

```bat
copy .env.example .env
notepad .env
```

Set at least:

```
TELEGRAM_BOT_TOKEN=<token of your existing bot>
TELEGRAM_CHAT_ID=<your group chat id, e.g. -1001234567890>
```

Optional: `TELEGRAM_DISABLE_NOTIFICATION=true` for silent delivery. All other settings are listed
(commented out, with defaults) in `.env.example`. Real environment variables take precedence
over `.env`. For a one-off session you can also use `set TELEGRAM_BOT_TOKEN=...` in cmd.

`.env` is git-ignored. Never put credentials in source files, `.env.example` or this README.

## Run

```bat
python main.py                 REM fetch, validate, save, send to Telegram
python main.py --dry-run       REM fetch, validate, save, PRINT the report; do not send
python main.py --no-telegram   REM fetch, validate, save; skip Telegram
python main.py --help
```

Start with `--dry-run` to check the output before the first real send.

Output (in `output\`, created automatically):

* `gold_silver_YYYYMMDD_HHMMSS.json` / `.txt` for each run (IST time stamp)
* `gold_silver_latest.json` / `.txt` always the most recent successful run
* `diagnostics\<timestamp>\` created only on failure: raw HTML, HTTP status and error details

Logs: `logs\gold_silver.log` (rotating). The bot token is redacted from all log output.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (saved, and delivered unless `--dry-run`/`--no-telegram`) |
| 1 | Unexpected error |
| 2 | Extraction or validation failed. Diagnostics saved, **nothing sent** |
| 3 | Configuration error (e.g. missing Telegram variables) |
| 4 | Report saved but Telegram delivery failed (message says how many parts were sent) |

### What "validation" means

A report is produced and sent only if **both** pages are fetched, parsed and pass these checks:
24K and 22K prices present; 24K > 22K > 18K; headline price equals table price; silver per-kg
is about 1000x per-gram; same city on both pages; and each page's date is at most
`MAX_DATA_AGE_DAYS` (default 1) days old in IST, which protects against stale/cached pages.
Warnings (for example gold and silver pages dated differently, no history table) are logged and
stored in the JSON but do not block sending.

### Telegram behaviour

* `sendMessage` over HTTPS, `parse_mode` not set (plain text), link previews disabled.
* Reports longer than 3,980 characters (limit is 4,096) are split **between lines/records**.
  Parts are labelled `[Part 1/2]`, and a table split across parts repeats its heading
  with "(continued)".
* Retries with exponential backoff for timeouts, connection errors, HTTP 429 (honours
  `retry_after`) and 5xx. Client errors (401, 400, 403, 404) are not retried and are explained.
  A request that times out after Telegram already accepted it can, rarely, cause a duplicate message.
* The bot must be a member of the group and allowed to post.

## Test

```bat
pip install -r requirements-dev.txt
python -m pytest -q
```

The tests use HTML fixtures in `tests\fixtures\` and a fake Telegram session, so they need no
network and send nothing. The fixtures are hand-built from the structure of the live pages,
so after your first `--dry-run` it is worth comparing the saved JSON with the live pages.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `CONFIG ERROR: TELEGRAM_BOT_TOKEN is not set` | `.env` missing or not next to `main.py`; or use `--dry-run` |
| `...does not look like a bot token` | Still the placeholder, or copied with extra characters. Format is `<digits>:<secret>` |
| `Unauthorized: the bot token is invalid` (401) | Wrong or revoked token. Get a new one from @BotFather |
| `Chat not found` (400) | Wrong `TELEGRAM_CHAT_ID`, or the bot was never added to the group. Group IDs are negative |
| `Forbidden` (403) | Bot was removed from the group or cannot post there |
| Group was upgraded to a supergroup | Telegram changes the ID; the error message shows the new `-100...` ID |
| `page is dated ... days old` | Source page is stale (or cached). Retry later; raise `MAX_DATA_AGE_DAYS` only if you accept older data |
| `No gold/silver prices found` | Page layout changed or a bot-check page was served. Open `output\diagnostics\<timestamp>\*.html` in a browser to see what was received |
| `HTTP 403/429/503` from goodreturns.in | Temporary blocking. Wait, then retry; do not lower the retry backoff |
| SSL / connection errors behind a proxy | Set `HTTPS_PROXY` (requests honours it). For corporate TLS inspection install the corporate CA |
| `python` not found | Use `py -3` instead, or reinstall Python with "Add to PATH" |
| Need more detail | `python main.py --dry-run --log-level DEBUG` and read `logs\gold_silver.log` |

## Scheduling on Windows (optional)

Task Scheduler action: program `path\to\gold-silver-telegram\.venv\Scripts\python.exe`,
arguments `main.py`, start in `path\to\gold-silver-telegram`. The exit code tells you whether
a run succeeded.
