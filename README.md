# Umrah Flight Watch

Telegram automation for tracking round-trip economy flight deals from Toronto
Pearson (`YYZ`) to Jeddah (`JED`) for Umrah travel.

Live channel: [Umrah Flight Watch](https://t.me/UmrahFlightWatch)

The bot scans Google Flights data through the open-source `flights` / `fli`
package, confirms promising date pairs with exact-date searches, and posts
clear Telegram reports for public subscribers.

## What It Does

- Runs scheduled discovery scans for 1-week, 2-week, and 1-month trip windows.
- Exact-checks the top calendar candidates before saving/reporting fares.
- Posts a weekly Telegram report with:
  - Cheapest exact-confirmed fares.
  - Best Overall fares, chosen for shorter travel time within a price guard.
  - Market rating based on recent exact-confirmed fare history.
  - A `Get Latest Deals` button that opens the bot with current fresh deals.
- Posts flash alerts when selected exact-confirmed fares are unusually cheap.
- Lets users request current deals with `/start` or `/current_deals`.
- Provides private admin commands for manual scans, reports, pause/resume, and
  provider status.

## Example Report

```text
🕋 Weekly YYZ → JED Flight Watch
May 25, 2026

1-Week Trips
💸 Cheapest: $1,412 CAD -- Jun 11 -> Jun 20 -- 9 days -- 2 stops -- Etihad Airways -- 43h 30m -- fare Normal -- flight Very Poor -- checked 1h ago
⏱️ Best Overall: $1,490 CAD -- Jun 11 -> Jun 20 -- 9 days -- 2 stops -- Etihad Airways -- 24h 35m -- fare Normal -- flight Poor -- checked 1h ago

2-Week Trips
💸 Cheapest: $1,362 CAD -- Jun 8 -> Jun 22 -- 14 days -- 2 stops -- Etihad Airways -- 43h 30m -- fare Normal -- flight Very Poor -- checked 1h ago
⏱️ Best Overall: $1,590 CAD -- Jun 8 -> Jun 23 -- 15 days -- 2 stops -- Etihad Airways -- 20h 55m -- fare Very High -- flight Good -- checked 1h ago

1-Month Trips
💸 Cheapest: $1,362 CAD -- May 26 -> Jun 24 -- 29 days -- 2 stops -- Etihad Airways -- 43h 30m -- fare Normal -- flight Very Poor -- checked 1h ago
⏱️ Best Overall: $1,590 CAD -- May 25 -> Jun 23 -- 29 days -- 2 stops -- Etihad Airways -- 20h 55m -- fare High -- flight Good -- checked 1h ago

📊 Market: Normal market -- 7.0/10

⚠️ Prices can change. Always verify the final price, baggage, and layovers before booking.
Send Feedback
```

## Example Current Deals DM

```text
🕋 Latest YYZ → JED Deals

1-Week Trips
💸 Cheapest: $1,412 CAD -- Jun 11 -> Jun 20 -- 9 days -- 2 stops -- Etihad Airways -- 43h 30m -- fare Normal -- flight Very Poor -- checked 12 min ago
⏱️ Best Overall: $1,490 CAD -- Jun 11 -> Jun 20 -- 9 days -- 2 stops -- Etihad Airways -- 24h 35m -- fare Normal -- flight Poor -- checked 12 min ago

2-Week Trips
No fresh exact-confirmed deal found.

1-Month Trips
💸⏱️ Cheapest + Best Overall: $1,590 CAD -- May 25 -> Jun 23 -- 29 days -- 2 stops -- Etihad Airways -- 20h 55m -- fare High -- flight Good -- checked 12 min ago

⚠️ Prices can change. Always verify the final price, baggage, and layovers before booking.
```

Current-deals requests read cached fresh active deals from the database. They do
not trigger scans or provider calls, and they are rate-limited per chat.

## Example Flash Alert

```text
🚨 Ultra-Cheap YYZ → JED Deal

Price/Dates: $899 CAD -- Jun 10 -> Jun 17
Trip length: 7 days
Stops: 1 stop
Airline: Saudia
Total travel time: 17h 40m
Layover: 3h 10m in JED
Baggage: Carry-on included
```

## Tech Stack

- Python 3.12+
- FastAPI
- APScheduler
- SQLAlchemy + Alembic
- PostgreSQL / Supabase
- Telegram Bot API
- Docker
- `flights` / `fli` provider package

## Setup

1. Create a Telegram bot with BotFather.
2. Add the bot as an admin to your Telegram channel.
3. Create a PostgreSQL database.
4. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

5. Fill in the required values:

   ```env
   TELEGRAM_BOT_TOKEN=
   TELEGRAM_BOT_USERNAME=
   TELEGRAM_CHANNEL_ID=
   TELEGRAM_ADMIN_CHAT_ID=
   DATABASE_URL=
   FEEDBACK_FORM_URL=
   FLI_DEFAULT_PRICE_CURRENCY=CAD
   FLI_CALL_TIMEOUT_SECONDS=90
   USD_TO_CAD_RATE=1.37
   DRY_RUN=true
   LOG_LEVEL=INFO
   ```

6. Install dependencies:

   ```bash
   python -m pip install -e .[dev]
   ```

7. Run database migrations:

   ```bash
   python -m alembic upgrade head
   ```

8. Start locally:

   ```bash
   python -m uvicorn app.main:app --reload
   ```

9. Test from Telegram:

   ```text
   /scan_now all
   /post_report
   /current_deals
   ```

Keep `DRY_RUN=true` until the report looks right. Set `DRY_RUN=false` only when
the bot is ready to post to the public channel.

## Docker

Build and run:

```bash
docker build -t umrah-flight-watch .
docker run --rm --env-file .env umrah-flight-watch python -m alembic upgrade head
docker run -d --name umrah-flight-watch --restart unless-stopped --env-file .env -p 8000:8000 umrah-flight-watch
```

View logs:

```bash
docker logs -f umrah-flight-watch
```

## Bot Commands

Public BotFather commands:

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

Only the configured `TELEGRAM_ADMIN_CHAT_ID` can run admin commands.

## Runtime Notes

- The provider can rate-limit requests, especially from cloud-hosted servers.
- Slow or stuck provider calls are capped by `FLI_CALL_TIMEOUT_SECONDS` so one
  stalled request does not freeze the hourly pipeline.
- Flight prices can change quickly and must be verified before booking.
- Links open Google Flights searches; final fare, baggage, and layovers should
  always be checked by the user.
- The bot stores historical fares to improve market ratings over time.
- Current deals are served from fresh `active_deals`; old fares stay in history
  but are not presented as current.
- US-hosted EC2 instances may receive provider prices in USD. The bot normalizes
  provider prices to CAD before saving; set `FLI_DEFAULT_PRICE_CURRENCY=USD`
  and keep `USD_TO_CAD_RATE` reasonably current if running from a US region.
- Currency normalization does not retroactively fix old rows. Clear suspect
  `price_history` and `active_deals` rows if USD prices were previously saved
  as CAD.

## Verification

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest
```

## License

MIT
