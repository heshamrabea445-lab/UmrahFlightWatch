# Umrah Flight Watch

Telegram automation for a public YYZ to JED round-trip economy flight-deal channel.

Version 1 uses only the open-source `flights` / `fli` package. It does not use SearchAPI, SerpApi, browser automation, cloaked scraping, user accounts, payments, private alerts, or a dashboard.

## Local Setup

1. Create a Telegram bot with BotFather.
2. Add the bot as admin to your Telegram channel.
3. Get `TELEGRAM_BOT_TOKEN`.
4. Get `TELEGRAM_CHANNEL_ID` as a public channel username or channel ID.
5. Get `TELEGRAM_ADMIN_CHAT_ID`.
6. Create a PostgreSQL database.
7. Copy the database connection string into `DATABASE_URL`.
8. Create a feedback form and copy its link.
9. Copy `.env.example` to `.env`.
10. Install dependencies:

   ```powershell
   python -m pip install -e .[dev]
   ```

11. Run Alembic migrations:

   ```powershell
   python -m alembic upgrade head
   ```

12. Run the app in `DRY_RUN=true`:

   ```powershell
   python -m uvicorn app.main:app --reload
   ```

13. In Telegram, run:

   ```text
   /scan_now all
   ```

14. Then run:

   ```text
   /post_report
   ```

15. Set `DRY_RUN=false` only after confirming output looks good.

## Runtime Behavior

- Scheduled scans use Toronto time:
  - Discovery scans run every hour.
  - The three trip categories run in parallel by default.
  - Each category exact-checks the top 10 calendar candidates.
  - Each candidate is checked with `CHEAPEST` and `TOP_FLIGHTS` exact-search modes.
  - `TOP_FLIGHTS` results feed the report's Best Overall pick when they stay within the price guard.
  - Best Overall heavily favors lower total travel time; stop count remains display-only.
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
- Strong alerts are price-first:
  - With enough 90-day history, a selected exact-confirmed deal alerts at or below
    `FLASH_ALERT_MEDIAN_RATIO` of the category cheapest-snapshot median.
  - Without enough 90-day history, alerts are limited to fares at or below
    `FLASH_ALERT_ABSOLUTE_FALLBACK_CAD`.
  - Suspicious-price detection is only a safety guard and uses
    `SUSPICIOUS_PRICE_AVERAGE_RATIO` of the category average.
- Friday `13:30` posts the weekly report.
- `/pause` pauses scheduled scans and channel posting; `/resume` restores them.
- Manual admin commands remain available while paused.
- Strong alerts require exact-date confirmation from the exact-search providers.

## Admin Commands

- `/status`
- `/usage`
- `/pause`
- `/resume`
- `/scan_now one_week|two_week|one_month|all`
- `/post_report`
- `/last_deals`
- `/provider`

Only `TELEGRAM_ADMIN_CHAT_ID` can use admin commands.

## Verification

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest
```
