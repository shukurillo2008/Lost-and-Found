# Campus Lost & Found

A university lost-and-found platform built as a three-service Docker application:

- a **Telegram bot** where students report lost or found items and receive match notifications;
- a **Django office panel** where staff receive items into storage, review matches and hand items back;
- a **background worker** that keeps matching, retention checks, report expiry and the daily office digest running.

All three services share one SQLite database and one media volume, so a report created in Telegram is immediately visible to the office, and a handover performed in the office is immediately reflected in the bot.

---

## Contents

- [Live access](#live-access)
- [Features](#features)
- [Architecture](#architecture)
- [Technology stack](#technology-stack)
- [Quick start with Docker](#quick-start-with-docker)
- [Environment variables](#environment-variables)
- [Seed data](#seed-data)
- [Office web interface](#office-web-interface)
- [Telegram bot](#telegram-bot)
- [Matching engine](#matching-engine)
- [Background worker](#background-worker)
- [Daily office digest](#daily-office-digest)
- [CSV export](#csv-export)
- [Data model](#data-model)
- [Internationalization](#internationalization)
- [Tests](#tests)
- [Privacy and security](#privacy-and-security)
- [Deployment](#deployment)
- [Demo and defense](#demo-and-defense)
- [Project structure](#project-structure)
- [Project status](#project-status)
- [Author](#author)

---

## Live access

| Service | Address |
| --- | --- |
| Office web application (local Docker) | <http://localhost:8000/> |
| Django administration | <http://localhost:8000/admin/> |
| Telegram bot | `@lost_and_found_ttpu_bot` |

> **Public deployment:** the public web URL is **pending**. The application is fully runnable with Docker as described below; the hosting URL will be added here once the deployment milestone is complete.

The Telegram bot handle is the one assigned to the configured `BOT_TOKEN`. If you run the project with your own token, use the username BotFather gave that bot.

---

## Features

### For students and finders (Telegram)

- First-run language selection in **Uzbek, Russian or English**; the choice can be changed later with `/settings`.
- Guided **"I lost something"** wizard: category, title, description, colour, building and area, date, optional photo, confirmation and edit step.
- Guided **"I found something"** wizard with the same fields plus custody choice (handed to the office or kept by the finder) and consent to share contact details with a possible owner.
- **Recent found items** browser with pagination and a "this is mine" action that creates a match suggestion for the chosen lost report.
- **My reports** list with the ability to cancel a report.
- Match notifications with inline **Yes / No** buttons; the answer is applied through the same decision logic as the office panel.
- **Share phone number** menu button (Telegram `request_contact`) so a finder can be reached if they opted in to contact sharing.
- When a match is confirmed, the lost reporter gets a message with the finder's **Telegram @username** and, when shared, **phone number**; without consent the office mediates the return.
- Handover notification when an item is returned.
- One-tap **reopen** button when a lost report is automatically expired after 90 days.
- Blocked-user middleware: blocked accounts cannot use the bot.

### For office staff (web)

- Login-protected, staff-only office panel with a branded dashboard.
- Dashboard metrics: items in storage, items expiring within 7 days, open lost reports, pending match suggestions, items returned this month.
- Charts: storage items by category, top lost-report locations, retention outlook, and an 8-week received / returned / disposed flow.
- Filterable, paginated storage inventory (search, category, shelf, received period, explicit date range, status).
- Fast item reception with optional prefill from a found report, photo upload and automatic next-free shelf code suggestion.
- Item detail page with photo, retention deadline, status timeline and match suggestions.
- Return (handover), dispose and transfer actions; dispose and transfer require a note, and every transition is written to the audit log.
- Confidential handover act: receiver name and **last four digits** of the student/staff ID.
- Lost-report list and detail with search, category, location, status and date-range filters.
- Found-report table with search, status, custody, category and date-range filters; reporter, contact-consent and linked-storage-item columns, plus a "mark as handed to office" action for reports the finder kept.
- Match review queue grouped by lost report, with confirm/reject decisions and score breakdowns.
- Reference-data management for locations, categories and colours, with delete guards and automatic translation of blank fields.
- Monthly inventory CSV export that follows the active status filter.
- Django admin for low-level data administration.
- Interface language switcher (Uzbek default, Russian, English).

### For the office group

- A daily Telegram digest (by default at 09:00 Asia/Tashkent) with retention warnings, overdue items, open reports, pending matches and today's totals.

---

## Architecture

```mermaid
flowchart LR
    student["Students and finders<br/>Telegram"] --> bot["bot service<br/>aiogram 3 · long polling"]
    staff["Office staff<br/>browser"] --> web["web service<br/>Django 5 · gunicorn"]
    bot --> db[("SQLite<br/>shared volume")]
    web --> db
    worker["worker service<br/>cycles · digest"] --> db
    bot --> tg["Telegram Bot API"]
    web --> tg
    worker --> tg
    web --> media[("media volume")]
    bot --> media
    worker --> media
    web --> static[("static volume<br/>WhiteNoise")]
```

The three containers are defined in `docker-compose.yml`:

| Service | Container | Command | Responsibility |
| --- | --- | --- | --- |
| `web` | `lnf_web` | migrate, collectstatic, gunicorn | Office UI, admin, CSV, media, outbound Telegram notifications |
| `bot` | `lnf_bot` | `python -m bot.main` | aiogram long polling, wizards, browsing, callback answers |
| `worker` | `lnf_worker` | `python worker/main.py` | Retention flags, report expiry, system matching, daily digest |

All services import the same Django settings module and talk to the same SQLite file through the Django ORM. SQLite runs in WAL mode with a busy timeout so concurrent web, bot and worker writes do not block each other indefinitely.

The web and worker services send Telegram messages through `web/bot_app/telegram_api.py`, a small `urllib` Bot API client. They do not import aiogram; only the bot service uses it.

---

## Technology stack

| Layer | Technology |
| --- | --- |
| Language | Python 3.11 |
| Web framework | Django 5.x |
| Telegram bot | aiogram 3.x (long polling, FSM wizards) |
| Database | SQLite with WAL mode and `busy_timeout` |
| WSGI server | Gunicorn |
| Static files | WhiteNoise |
| Images | Pillow |
| Translation | deep-translator (MyMemory) with an offline switch |
| Front end | Django templates, Bootstrap 5.3.8 (vendored), Tabler Icons, Chart.js, Select2, jQuery |
| Containers | Docker, Docker Compose |
| Tests | Django test runner |

The office UI uses vendored front-end assets only; no CDN is required at runtime. Navigation and actions use Tabler icons; emoji are stored only as category reference data.

---

## Quick start with Docker

### Prerequisites

- Docker Desktop with Docker Compose v2
- Git

### 1. Clone the repository

```bash
git clone https://github.com/shukurillo2008/Lost-and-Found.git
cd "university project"
```

### 2. Create the environment file

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS / Linux:

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```dotenv
DJANGO_SECRET_KEY=replace-with-a-long-random-string
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,web
BOT_TOKEN=123456789:your-telegram-bot-token
OFFICE_GROUP_ID=-1000000000000
SEED_ADMIN_USERNAME=admin
SEED_ADMIN_PASSWORD=choose-a-strong-password
```

`OFFICE_GROUP_ID` is the numeric chat id of the staff Telegram group that receives the digest. The bot must be a member of that group.

Never commit `.env`; it is already excluded by `.gitignore`.

### 3. Build and start the services

```bash
docker compose up --build -d
```

The `web` container waits for the database, runs migrations, collects static files and then starts Gunicorn. The bot and worker start after the web health check passes.

Check the state:

```bash
docker compose ps
docker compose logs -f web
```

### 4. Load demo data

```bash
docker compose exec web python web/manage.py seed_demo
```

`seed_demo` is idempotent and deterministic: it uses `get_or_create` natural keys and `random.seed(42)`, so it can be run repeatedly without duplicating rows. If `SEED_ADMIN_USERNAME` and `SEED_ADMIN_PASSWORD` are set, the first run also creates the office superuser.

If the database must stay otherwise empty — for example a clean demo where every report is entered live — fill only the reference tables the bot and the office forms need:

```bash
docker compose exec web python web/manage.py seed_reference
```

`seed_reference` creates the same 20 campus locations, 9 categories and 12 colours as the full seeder, but no users, reports or storage items. It is idempotent and safe to run before `seed_demo` (the full seeder then only adds the transactional data).

To create an additional administrator manually:

```bash
docker compose exec web python web/manage.py createsuperuser
```

### 5. Open the application

- Office panel: <http://localhost:8000/>
- Django admin: <http://localhost:8000/admin/>
- Bot: send `/start` to `@lost_and_found_ttpu_bot` (or to the bot belonging to your `BOT_TOKEN`).

### 6. Apply environment changes

Environment variables are read when a container starts. After editing `.env`, recreate the services:

```bash
docker compose up -d --force-recreate web bot worker
```

### Stop and clean up

```bash
docker compose down          # stop containers, keep volumes
docker compose down -v       # stop containers and delete the database/media volumes
```

---

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | insecure development fallback | Django secret key; set a long random value in production |
| `DJANGO_DEBUG` | `False` | Debug mode; keep `False` outside development |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,web` | Comma-separated host names accepted by Django |
| `DJANGO_TIMEZONE` | `Asia/Tashkent` | Local timezone for dates, digest hour and reports |
| `BOT_TOKEN` | empty | Telegram bot token; when empty, outbound notifications are safe no-ops |
| `OFFICE_GROUP_ID` | empty | Numeric staff-group chat id for the daily digest |
| `SEED_ADMIN_USERNAME` | empty | Superuser username created by `seed_demo` on first run |
| `SEED_ADMIN_PASSWORD` | empty | Superuser password created by `seed_demo` on first run |
| `SQLITE_PATH` | `/app/data/db.sqlite3` in Compose | SQLite database file |
| `MEDIA_ROOT` | `/app/media` in Compose | Uploaded photos |
| `STATIC_ROOT` | `/app/staticfiles` in Compose | Collected static files |
| `WORKER_MATCH_INTERVAL_MINUTES` | `10` | Matching/retention/expiry cycle interval |
| `WORKER_INTERVAL_SECONDS` | unset | Legacy override for the cycle interval; wins when set |
| `WORKER_DIGEST_HOUR` | `9` | Local hour at which the daily digest becomes due |
| `DIGEST_RETRY_MINUTES` | `10` | Cooldown before retrying a failed digest |
| `AUTO_TRANSLATE` | `True` | Fill blank `name_en` / `name_ru` fields through the online translator |
| `MYMEMORY_EMAIL` | unset | Optional MyMemory contact email for a higher translation quota |

---

## Seed data

`python web/manage.py seed_demo` creates a realistic dataset for demonstration and grading:

| Data | Count |
| --- | --- |
| Buildings | 3 |
| Areas / locations | 20 |
| Categories with retention policies | 9 |
| Colours | 12 |
| Office staff data owners | 4 (+1 admin from `.env`) |
| Telegram users | 30 |
| Lost reports | 48 (40 seeded reports + 8 claim reports for handover history) |
| Found reports | 30 |
| Stored items | 25 (18 linked to found reports, 7 walk-ins) |
| Handover acts | 8 |
| Confirmed match suggestions | 8 |
| Item status-log rows | 11 |

Report dates are spread over the last two months so the dashboard charts and date filters show meaningful data. The handover history is internally consistent: each returned item has a confirmed suggestion, a handover act, a status-log entry and the matching lost/found report statuses.

The mock data is **fully trilingual**. Every lost and found report is generated in Uzbek (the primary language) and stores real Russian and English translations in its `title_uz/_ru/_en` and `description_uz/_ru/_en` streams, so the language tabs on the report pages show three genuinely different texts instead of the same English string three times. Colours, locations and categories are likewise seeded in all three languages, and office notes (handover acts, disposal/transfer audit entries) are written in Uzbek.

The four `office.*` accounts are data owners for the seeded history. They are not intended as login accounts; sign in with the superuser created from `SEED_ADMIN_USERNAME` / `SEED_ADMIN_PASSWORD`.

After the first worker matching cycle, the seeded open reports also get a handful of **pending system suggestions**, so the match review queue is populated for the demo. Seeded Telegram users have fake ids, so notifications to them are rejected by Telegram and logged as warnings without breaking the cycle.

### Reference data only

`python web/manage.py seed_reference` fills just the reference layer — 3 buildings / 20 areas, 9 categories with their retention policies, and 12 colours — and leaves reports, storage items and accounts untouched. Use it when the database should stay empty (for example a defence run where all transactional data is entered live). Both commands share the same tables, so `seed_reference` followed by `seed_demo` never duplicates reference rows.

---

## Office web interface

All office pages require an authenticated **staff** user. Anonymous visitors are redirected to the login page; authenticated non-staff users receive a branded 403 page.

| URL | Page |
| --- | --- |
| `/` | Dashboard: metrics, charts and quick links |
| `/storage/` | Storage inventory with filters and pagination |
| `/storage/receive/` | Receive a new item into storage |
| `/storage/items/<id>/` | Item detail, status timeline, match suggestions, actions |
| `/storage/items/<id>/handover/` | Confidential handover act |
| `/storage/export/` | Monthly inventory CSV export |
| `/reports/lost/` | Lost-report list |
| `/reports/found/` | Found-report list (custody, consent, linked item) |
| `/reports/lost/<id>/` | Lost-report detail with match review |
| `/reports/matches/` | Global match review queue |
| `/catalog/locations/` | Campus locations (list, create, edit, delete) |
| `/catalog/categories/` | Categories and colours (list, create, edit, delete) |
| `/admin/` | Django administration |
| `/accounts/login/` | Staff login |
| `/accounts/logout/` | Staff logout |
| `/lang/<code>/` | Switch the office interface language |

### Storage workflow

1. A finder submits a found report in the bot, or brings an item directly to the office.
2. Staff open **Receive item**, optionally link an open found report to prefill the text, choose a category/colour, add a photo and confirm the suggested shelf code.
3. Saving creates the `StoredItem`, computes `retention_until` from the category's retention policy and writes the first status-log row. A linked found report becomes `registered`, and any confirmed match that was made while the finder still held the item is re-pointed at the new stored item.
4. The worker scores the item against open lost reports and creates system suggestions.
5. Staff confirm a suggestion on the lost-report page or in the match queue.
6. The handover form opens pre-filled with the confirmed claimant; staff enter the receiver's name and the last four digits of their ID.
7. The handover is atomic: it creates the `Handover` record, marks the item `returned`, writes the status log, marks the linked found report `returned` when applicable, marks the confirmed lost claim `returned` when one exists, and notifies the reporter in Telegram.
8. Items can also be **disposed** or **transferred** from the item page, with a mandatory note. These actions are staff-only and always logged.

**Kept-by-finder items** stay with the finder after the report is submitted. If the finder later brings the item in, staff use the found-report table's **Mark as handed to office** action; the report then appears in the receive selector, so the normal receive → handover flow resolves the confirmed claim. The handover form never pre-fills the finder as the receiver.

Retention is derived, not a flag column. The worker reports items that are expiring or overdue, but it never disposes anything automatically: the course specification requires every storage status change to be a staff decision.

---

## Telegram bot

### Commands

| Command | Purpose |
| --- | --- |
| `/start` | Register the user, choose a language on first use, open the main menu |
| `/settings` | Change the interface language |

### Main menu

- **I lost something** — starts the lost-report wizard.
- **I found something** — starts the found-report wizard.
- **Recent found items** — browses recent found reports with photos and a "this is mine" button.
- **My reports** — lists the user's own reports and allows cancellation.

### Report wizards

Both wizards are implemented as aiogram FSM state machines and support **Back**, **Cancel** and a final **summary** step with **Confirm** / **Edit** actions.

Lost flow: category → title → description → colour → building → area → date lost → optional photo → summary.

Found flow: category → title → description → colour → building → area → date found → optional photo → custody → contact-sharing consent → summary.

Titles and descriptions are stored in the reporter's language and automatically translated into the other two language streams when `AUTO_TRANSLATE` is enabled. Re-saving a report without changing its canonical title/description leaves the existing translations untouched, even if the reporter later switches language.

### Notifications

- A new match suggestion sends the reporter an "is this your item?" message with inline **Yes** / **No** buttons. The answer is validated against the suggestion owner and applied through `matching.services.apply_decision`.
- A handover sends the reporter a plain "your item was returned" message with the handover date.
- An expired report sends a one-tap **Reopen** button. Reopening resets the 90-day expiry clock through `LostReport.reopened_at`.

When `BOT_TOKEN` is empty, or the user has blocked the bot, outbound notifications are logged and skipped without breaking the web request or the worker cycle.

---

## Matching engine

The single source of truth is `web/matching/engine.py`. The worker, the office review pages and the bot all use the same function, so a weight change re-scores the whole system consistently.

### Scoring rules

| Criterion | Points |
| --- | --- |
| Category identity | **Required**; a different category scores 0 and stops scoring |
| Same colour | +3 |
| Item found on or after the lost date, within 14 days | +2 |
| Same building | +2 |
| Same area (in addition to the building bonus) | +1 |
| Shared words between title + description | +1 per word, capped at +4 |

The worker creates a system suggestion only when the total score is **strictly greater than 5**. A pair with the same category, colour and time scores exactly 5 and is therefore not auto-suggested; it needs one more signal (location or shared words).

### Example

Same category, same colour, found two days after the loss, same building and area, two shared words:

```text
3 (colour) + 2 (time) + 2 (building) + 1 (area) + 2 (words) = 10
```

The full breakdown is stored verbatim in `MatchSuggestion.score_breakdown`, including diagnostic fields such as the shared words and both dates. The office review card displays the contributing criteria and their points, so staff can see exactly why a pair scored what it scored.

### Decision lifecycle

```text
suggested ──confirm──> confirmed
    │                      │
    └──────reject──────────┴──> rejected
```

- Suggestions can come from the **system** worker, from **staff**, or from a **user** pressing "this is mine".
- The pair `(lost_report, stored_item)` is unique, so the worker never duplicates a suggestion. The worker also tracks the found report behind an item, so a "this is mine" suggestion is not duplicated once the finder hands the item in.
- Confirming a fresh suggestion moves the lost report from `open` to `matched`. A found-report-only suggestion resolves the linked stored item when one exists, so the handover can find the claim.
- Rejecting the last confirmed suggestion moves the report back to `open`.
- When a report expires, its still-pending suggestions are rejected in the same worker pass and can no longer be decided.
- A confirmed suggestion pre-fills the handover receiver from the claimant; the handover itself remains a separate staff action. Confirming never happens automatically.
- The reporter's Yes/No answer and the staff decision use the same transition service (`web/matching/services.py`).

---

## Background worker

The worker starts one asynchronous loop with a **30-second heartbeat**. The main work cycle runs every `WORKER_MATCH_INTERVAL_MINUTES` (default **10 minutes**); the legacy `WORKER_INTERVAL_SECONDS` value overrides the interval when present.

Each work cycle performs three preserving jobs:

1. **Retention cycle** — counts items expiring within 7 days and items past their retention deadline ("ready for disposal"). It never changes a status.
2. **Expiry cycle** — open lost reports older than 90 days become `expired`, their still-pending match suggestions are rejected, and the reporter receives a reopen button in the bot. A report reopened from the bot is not expired again on the next pass.
3. **Matching cycle** — every open lost report is scored against every in-storage item. Pairs above the system threshold become `MatchSuggestion` rows with `created_by="system"`, and the reporter is notified. Existing pairs are skipped, including a pair already covered by a suggestion that points at the item's found report.

The digest job runs on every heartbeat (see below). Failures are logged and retried on the next tick; a failed work cycle never stops the service.

The worker does **not** dispose items and does **not** confirm matches. Both remain staff decisions.

---

## Daily office digest

Once per local day, at `WORKER_DIGEST_HOUR` (default **09:00 Asia/Tashkent**), the worker posts a digest to `OFFICE_GROUP_ID`. The message summarises:

- items whose retention deadline falls within the next 7 days;
- items already past the deadline ("ready for disposal", staff-only);
- open lost reports and pending match suggestions;
- today's received, returned and disposed totals.

The digest text is written in Uzbek for the office team. Sending is idempotent per local date: `DigestRun.sent_on` is unique, so a worker restart or a duplicate tick cannot send the same day twice. A failed send is retried after `DIGEST_RETRY_MINUTES` (default 10) and gives up after 5 attempts for that day; the next day starts fresh.

The text is capped below Telegram's 4096-character message limit. Item lines are added whole, so the cap can never split an HTML tag; when items are hidden, a trailing "… yana N ta" note keeps the count honest.

If `BOT_TOKEN` or `OFFICE_GROUP_ID` is missing or invalid, the digest is a safe no-op and the reason is logged.

---

## CSV export

`GET /storage/export/` exports the items **received in a chosen month** (default: the current month).

| Parameter | Values | Default |
| --- | --- | --- |
| `month` | `YYYY-MM` | current month |
| `status` | `in_storage`, `returned`, `disposed`, `transferred`, `all` | `in_storage` |

The export is status-aware: the default file is the physical inventory, and the export link on the storage page carries the currently active status filter, so the downloaded file matches the list on screen. Invalid status values fall back to `in_storage`; a malformed month falls back to the current month. The month and the received date both follow `settings.TIME_ZONE` (Asia/Tashkent), so an item received late on the last UTC day of a month lands in the correct local month.

The file is UTF-8 with a BOM (so Excel opens it correctly), has localized headers and a filename such as `inventory-2026-11.csv`.

---

## Data model

```mermaid
erDiagram
    TelegramUser {
        int id PK
        bigint telegram_id
        string display_name
        string language
        bool is_blocked
    }
    LostReport {
        int id PK
        string title
        date date_lost
        string status
    }
    FoundReport {
        int id PK
        string title
        date date_found
        string custody
        string status
    }
    StoredItem {
        int id PK
        string shelf_code
        string title
        string status
        date retention_until
    }
    MatchSuggestion {
        int id PK
        int score
        string status
        string created_by
    }
    Handover {
        int id PK
        string receiver_name
        string receiver_id_last4
        datetime handed_at
    }
    ItemStatusLog {
        int id PK
        string old_status
        string new_status
        string note
    }
    Category {
        int id PK
        string name_uz
        int retention_days
    }
    Color {
        int id PK
        string name_uz
    }
    Location {
        int id PK
        string building_uz
        string area_uz
    }
    DigestRun {
        int id PK
        date sent_on
        int attempts
    }
    User {
        int id PK
        string username
        bool is_staff
    }

    TelegramUser ||--o{ LostReport : "reports"
    TelegramUser ||--o{ FoundReport : "reports"
    Category ||--o{ LostReport : "classifies"
    Category ||--o{ FoundReport : "classifies"
    Category ||--o{ StoredItem : "classifies"
    Color ||--o{ LostReport : "colours"
    Color ||--o{ FoundReport : "colours"
    Color ||--o{ StoredItem : "colours"
    Location ||--o{ LostReport : "lost at"
    Location ||--o{ FoundReport : "found at"
    FoundReport |o--o| StoredItem : "becomes"
    LostReport ||--o{ MatchSuggestion : "has"
    StoredItem |o--o{ MatchSuggestion : "candidate"
    FoundReport |o--o{ MatchSuggestion : "candidate"
    StoredItem ||--o{ ItemStatusLog : "audit trail"
    StoredItem ||--o| Handover : "closed by"
    LostReport |o--o{ Handover : "claimed by"
    User ||--o{ StoredItem : "received by"
    User ||--o{ Handover : "registers"
    User |o--o{ MatchSuggestion : "reviews"
    User |o--o{ ItemStatusLog : "changes"
```

Key constraints:

- `FoundReport` ↔ `StoredItem` is one-to-one and optional on both sides: a found report may become a stored item, and a walk-in item may have no found report.
- `MatchSuggestion` is unique on `(lost_report, stored_item)` and must reference at least one source (stored item or found report).
- `StoredItem` ↔ `Handover` is one-to-one: an item can leave storage only once.
- `DigestRun.sent_on` is unique and provides the once-per-day digest guarantee.
- Reference rows use `PROTECT` foreign keys where deleting them would break historical reports or storage records.

---

## Internationalization

The project has three interface languages: **Uzbek (default), Russian and English**.

### Office panel

- Django gettext catalogs live in `web/locale/uz/LC_MESSAGES/django.po` and `web/locale/ru/LC_MESSAGES/django.po`; compiled `.mo` files are committed alongside them.
- Message ids are written in English and translated into Uzbek and Russian.
- The current catalog covers **257 msgids**.
- The language is stored in the `office_language` cookie and can be switched from the header (`/lang/<code>/`).

### Telegram bot

Bot strings live in `bot/strings.py` as three explicit dictionaries. The user's language is stored on `TelegramUser.language` and can be changed with `/settings` at any time.

### Reference data and reports

- Categories, colours and locations store `_uz`, `_en` and `_ru` columns; Uzbek is canonical.
- Lost and found reports store translated title/description streams. The reporter's language stream is filled directly and the other two are auto-translated when `AUTO_TRANSLATE=True`.
- The office UI and the bot fall back to the canonical text when a translation is blank.

The compiled `.mo` files are committed. After editing a `.po` file, rebuild it with GNU gettext (`msgfmt`) or Babel before restarting the web service.

---

## Tests

The graded test suite uses Django's test runner:

```bash
docker compose exec -T -e DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,web,testserver web python web/manage.py test catalog matching storage bot_app reports
```

The `testserver` host is required because Django's test client sends requests with that host name.

Current result: **118 tests, all passing**.

| App | Covered behaviour |
| --- | --- |
| `catalog` | Reference-data rules, translation fallbacks, seed consistency and idempotency, location delete guard counting both report kinds |
| `matching` | Scoring rules, threshold, duplicate-suggestion guards across stored items and found reports, confirm/reject transitions, closed-report and unavailable-item guards, one confirmed match per report, expiry closing pending suggestions, found-only claims resolving the stored item |
| `storage` | Retention calculation, status transitions, handover close-out, audit logs, status-aware CSV export with local dates, receive-form validation, shelf availability probe, item-delete safety |
| `reports` | Office found-report table: staff gate, filters, linked item and consent columns, custody handover marker, language-stream stability |
| `bot_app` | Telegram user model, digest idempotency, retry behaviour and the 4096-character cap, notification safety |

Additional checks run during development:

```bash
docker compose exec web python web/manage.py check
docker compose exec web python web/manage.py makemigrations --check --dry-run
```

The second command must report `No changes detected`.

---

## Privacy and security

- **ID data minimisation.** A handover stores only the receiver's name and the **last four digits** of their student/staff ID. The full ID is never requested, stored or logged. The handover act is visible only inside the staff office.
- **Contact sharing is opt-in.** A finder chooses whether their contact details may be shared with a possible owner. Without consent, the office mediates the return.
- **Staff-only data.** Every office page, report photo and uploaded item photo requires both authentication and `is_staff`. Anonymous users are redirected to login; non-staff users get a 403. Media files are served through a gated Django view, not a public directory.
- **CSRF and session protection.** All state-changing office actions are POST requests protected by Django's CSRF middleware. Login uses Django's authentication system and safe `next` validation.
- **Secrets stay out of the repository.** `DJANGO_SECRET_KEY`, `BOT_TOKEN`, `OFFICE_GROUP_ID` and the seed admin password are read from `.env`, which is git-ignored. The repository contains only `.env.example`.
- **Safe notification failures.** Missing tokens, blocked users and Telegram API errors are logged and treated as no-ops; they never expose internals to the user or break a worker cycle.
- **No automatic storage or match decisions.** The worker can expire old lost reports, but it cannot dispose of a stored item or confirm a match. Those actions require a staff member and are written to the audit log.
- **Blocked users.** The bot middleware refuses updates from users marked as blocked.
- **Least-privilege bot use.** The bot needs to be a member of the office group to deliver the digest; it does not need administrator rights for normal operation.

---

## Deployment

### Supported deployment: Docker Compose + Caddy

The repository deploys as four containers on one host: `web` (gunicorn), `bot` (long polling), `worker`, and `caddy` (HTTPS). Only Caddy publishes ports; the bot and worker make outbound connections only, and the web container is reachable only on the Compose network.

1. Point the domain's A/AAAA record at the host.
2. Copy `.env.example` to `.env` and set:
   - `DJANGO_SECRET_KEY` — a long random string;
   - `DJANGO_DEBUG=False`;
   - `DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,web,<domain>`;
   - `DJANGO_CSRF_TRUSTED_ORIGINS=https://<domain>`;
   - `DJANGO_HTTPS=True`;
   - `LNF_DOMAIN=<domain>`;
   - `BOT_TOKEN` and `OFFICE_GROUP_ID`.
3. Build and start everything with the production overlay:

   ```bash
   docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
   ```

   The overlay removes the web container's host port, adds Caddy on 80/443 and mounts `deploy/Caddyfile`, which proxies to `web:8000`.
4. Allow inbound TCP 80/443 (and UDP 443 for HTTP/3) in the host firewall. No other port is exposed by the overlay.
5. Caddy obtains and renews the Let's Encrypt certificate automatically; open `https://<domain>/admin/` and change the seeded admin password, or create a superuser:

   ```bash
   docker compose exec web python web/manage.py createsuperuser
   ```

6. Keep the `sqlite_data`, `media_data`, `static_data` and `caddy_data` volumes on persistent storage.
7. Run exactly **one** bot container (long polling allows only one poller per token) and one worker container.
8. Back up the SQLite database and the media volume together; they form one consistent dataset.

`DJANGO_HTTPS=True` enables secure session/CSRF cookies and HSTS (one year by default, override with `DJANGO_HSTS_SECONDS`). `SECURE_PROXY_SSL_HEADER` makes Django trust the proxy's `X-Forwarded-Proto: https`; the proxy owns the HTTP→HTTPS redirect, so the container health check stays on plain HTTP. Without a real domain, set `LNF_DOMAIN=localhost`: Caddy then uses its internal CA and browsers show a certificate warning.

### Public URL

> **Pending.** The public web address will be recorded here after the deployment milestone. Until then, the local Docker URL above is the supported way to run the application.

### Telegram bot

`@lost_and_found_ttpu_bot` is the bot handle used by this project. It runs while the `bot` container is running and the configured token is valid.

---

## Demo and defense

- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) — a 6–8 minute, scene-by-scene recording plan with the exact pages, bot flows and commands.
- [`docs/DEFENSE_NOTES.md`](docs/DEFENSE_NOTES.md) — architecture map, requirement coverage, design trade-offs, a Q&A bank and a live-change rehearsal.

---

## Project structure

```text
.
├── bot/                         aiogram 3 bot service
│   ├── main.py                  entrypoint, routers, long polling
│   ├── handlers.py              /start, /settings, fallback
│   ├── wizards.py               lost/found FSM wizards
│   ├── browse.py                recent items, "this is mine", my reports
│   ├── notify.py                match / handover / reopen callbacks
│   ├── keyboards.py             reply and inline keyboards
│   ├── states.py                FSM state groups
│   ├── strings.py               uz / ru / en bot strings
│   └── middleware.py            blocked-user middleware
├── web/                         Django project
│   ├── manage.py
│   ├── config/                  settings, URLs, WSGI/ASGI, SQLite hooks
│   ├── catalog/                 Category, Color, Location, seed_demo, translation
│   ├── bot_app/                 TelegramUser, DigestRun, Bot API client, notifications, digest
│   ├── reports/                 LostReport, FoundReport
│   ├── storage/                 StoredItem, ItemStatusLog, retention rules
│   ├── matching/                MatchSuggestion, Handover, scoring engine, decision service
│   ├── office/                  staff web UI (views + URLs, no forms.py)
│   ├── templates/               Bootstrap templates
│   ├── static/                  vendored Bootstrap, Tabler Icons, Chart.js, Select2, jQuery
│   └── locale/                  uz / ru gettext catalogs
├── worker/
│   └── main.py                  retention, expiry, matching and digest loop
├── deploy/
│   ├── Caddyfile                HTTPS reverse proxy for the office UI
│   └── docker-compose.prod.yml  production overlay (Caddy, web port removed)
├── docs/
│   ├── DEMO_SCRIPT.md           scene-by-scene demo recording plan
│   └── DEFENSE_NOTES.md         architecture, Q&A and live-change rehearsal
├── Dockerfile                   Python 3.11 image
├── docker-compose.yml           web, bot and worker services
├── requirements.txt
├── .env.example
└── README.MD
```
---

## Project status

Implemented and verified:

- [x] Docker Compose skeleton with three services and shared volumes
- [x] Domain models, migrations and SQLite WAL configuration
- [x] Deterministic demo seeder with handover history
- [x] Telegram bot with trilingual onboarding, report wizards, browsing and notifications
- [x] Office dashboard, storage workflow, lost-report review and reference-data management
- [x] Shared matching engine with score breakdowns and confirm/reject lifecycle
- [x] Worker retention flags, 90-day report expiry and system suggestions
- [x] Daily office digest with per-date idempotency
- [x] Status-aware monthly CSV export
- [x] Uzbek / Russian / English office catalogs
- [x] Production HTTPS configuration (Caddy overlay, secure cookies, HSTS, CSRF origins)
- [x] Demo script and defense Q&A notes (`docs/`)
- [x] 118 automated Django tests

Remaining roadmap items:

- [ ] Public deployment with a recorded web URL
- [ ] Record the demo video and rehearse the defense
- [ ] Bonus: printable QR labels for shelf items
- [ ] Bonus: public web search for found items
- [ ] Bonus: CI pipeline

Known limitations:

- SQLite is a single-host database; the project is designed for one Docker host, not horizontal scaling.
- The bot uses long polling, so only one bot process may run per token.
- Automatic translation requires network access; set `AUTO_TRANSLATE=False` for fully offline operation.
- Stored items hold a single `title`/`description` pair (no translation columns), so shelf records are stored in the primary language, Uzbek; reports themselves are fully trilingual.
- The public web deployment is not published yet; the local Docker setup is fully functional.

---

## Author

University course project — **Campus Lost & Found**.

Built with Django, aiogram and Docker Compose.
