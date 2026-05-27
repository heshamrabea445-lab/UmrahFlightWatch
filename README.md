# Umrah Flight Watch

Private codebase for a public YYZ to JED round-trip economy flight-deal Telegram channel.

Version 1 uses only the open-source `flights` / `fli` package. It does not use SearchAPI, SerpApi, browser automation, cloaked scraping, user accounts, payments, private DMs, or a dashboard.

## Local Setup

1. Create a Telegram bot with BotFather.
2. Add the bot as admin to your Telegram channel.
3. Get `TELEGRAM_BOT_TOKEN`.
4. Get the bot username from BotFather and copy it into `TELEGRAM_BOT_USERNAME`.
5. Get `TELEGRAM_CHANNEL_ID` as a public channel username or channel ID.
6. Get `TELEGRAM_ADMIN_CHAT_ID`.
7. Create a PostgreSQL database.
8. Copy the database connection string into `DATABASE_URL`.
9. Create a feedback form and copy its link.
10. Copy `.env.example` to `.env`.
11. Install dependencies:

   ```powershell
   python -m pip install -e .[dev]
   ```

12. Run Alembic migrations:

   ```powershell
   python -m alembic upgrade head
   ```

13. Run the app in `DRY_RUN=true`:

   ```powershell
   python -m uvicorn app.main:app --reload
   ```

14. In Telegram, run:

   ```text
   /scan_now all
   ```

15. Then run:

   ```text
   /post_report
   ```

16. Set `DRY_RUN=false` only after confirming output looks good.

## Runtime Behavior

- Scheduled scans use Toronto time:
  - Discovery scans run every hour.
  - The three trip categories run in parallel by default.
  - Each category exact-checks the top 10 calendar candidates.
  - Each candidate is checked with `CHEAPEST` and `TOP_FLIGHTS` exact-search modes.
  - Best Overall is the fastest exact-confirmed result that stays within the price guard.
  - Stop count remains display-only.
- Set `DISCOVERY_CATEGORY_WORKERS=1` if the flight provider starts throttling.
- Reports hide active deals older than `REPORT_MAX_DEAL_AGE_HOURS`.
- Older deals remain in `price_history`, but are not presented as current report fares.
- Fare labels, market rating, and flash-alert medians use one baseline:
  `MARKET_BASELINE_DAYS` of cheapest exact-confirmed scan snapshots per category.
- Fare labels use median-ratio bands against that baseline: Excellent at 85% or less
  of median, Good at 95% or less, Normal at 106% or less, High at 120% or less.
- Keep `PRICE_HISTORY_DAYS` at least as large as `MARKET_BASELINE_DAYS`.
- Exact-search volume is roughly doubled because Cheapest and Best Overall use separate
  provider-ranked exact searches.
- Strong public channel alerts are price-first:
  - With enough 90-day history, a selected exact-confirmed deal alerts at or below
    70% of the category cheapest-snapshot median.
  - Without enough 90-day history, alerts are limited to fares at or below
    $750 CAD.
  - Suspicious-price detection is only a safety guard and uses
    20% of the category average.
- Friday `13:30` posts the weekly report.
- `/pause` pauses scheduled scans and channel posting; `/resume` restores them.
- Manual admin commands remain available while paused.
- Strong alerts require exact-date confirmation from the exact-search providers.
- Weekly reports include a `Get Latest Deals` button when `TELEGRAM_BOT_USERNAME`
  is set. The button opens the bot DM with fresh current deals.
- `/start` and `/current_deals` are public, read-only commands. They never trigger
  scans or provider calls.

## Tuning Constants

The following thresholds are intentionally code-level constants, not environment knobs:

- `MIN_HISTORY_ROWS` (20) in `app/services/market_baseline.py`
- `EXACT_SEARCH_TOP_N` (3) in `app/jobs/scan_jobs.py`
- `DEFAULT_BEST_VALUE_*` in `app/services/deal_selection.py`
- `DEFAULT_FLASH_ALERT_*` in `app/services/deal_selection.py`
- `DEFAULT_SUSPICIOUS_PRICE_AVERAGE_RATIO` in `app/services/deal_scoring.py`

## Admin Commands

Public BotFather command list:

```text
start - Open the bot and get current Umrah flight deals
current_deals - Show the latest fresh YYZ to JED deals
```

Private admin commands:

```text
/status
/usage
/pause
/resume
/scan_now one_week|two_week|one_month|all
/post_report
/last_deals
/provider
```

Only `TELEGRAM_ADMIN_CHAT_ID` can use admin commands.

## Verification

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest
```
