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

- Daily scans use Toronto time:
  - `09:00` scans 1-week trips.
  - `14:00` scans 2-week trips.
  - `20:00` scans 1-month trips.
- Friday `13:30` posts the weekly report.
- `/pause` pauses scheduled scans and channel posting; `/resume` restores them.
- Manual admin commands remain available while paused.
- Strong alerts require exact-date confirmation from `fli`.

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
