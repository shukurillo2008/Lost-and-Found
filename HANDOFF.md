# Campus Lost & Found — Agent Handoff Document

> Read this first. A new agent session should be able to continue this project
> exactly from this point after reading only this file plus the repository.

---

## 1. Project objective

Phase-based "Campus Lost & Found" system for a university:
- **Django 5.x web app** (staff-facing "Warehouse Management System" — milestone 5+)
- **aiogram 3.x Telegram bot** (@lost_and_found_ttpu_bot, long polling)
- **async worker orchestrator** (Docker Compose service `worker`)
- **SQLite** on a shared Docker volume configured with `PRAGMA journal_mode=WAL`
  and `PRAGMA busy_timeout=5000`.

### Operational protocol (agreed with the user)
- Work **one milestone at a time** (spec's rollout), present a milestone report
  with verification evidence, and **do not start the next milestone until the
  user explicitly replies "Proceed to Milestone N"**.
- End every milestone report with a ready **git commit message** (fenced code
  block). Do NOT commit unless the user explicitly asks.
- The user writes in Uzbek (Roman script with ʻ apostrophe); milestone reports
  have been written in English with Uzbek summaries at the end.

---

## 2. Environment

| What | Value |
|---|---|
| Host OS | Windows, PowerShell 5.1 (`bash` tool runs PowerShell) |
| Working dir | `C:\projects\university project` (**literal space in the path**) |
| Git | repo initialized; **all M3/M4 work is still UNCOMMITTED** (modified + untracked files, see `git status`) |
| Host Python | 3.14 (Django check/seed run locally with `python -X utf8`) |
| Container Python | 3.11 (`python:3.11-slim`) |
| Docker | Docker Desktop (sometimes needs manual start / `docker info` poll) |
| Bot token | real, in `.env` ONLY — **never commit, never paste into reports** |

### Docker layout
- Services: `web` (gunicorn + WhiteNoise), `bot` (aiogram), `worker` (heartbeat placeholder; real scheduler comes later).
- Named volumes: `universityproject_sqlite_data` (/app/data), `universityproject_media_data` (/app/media), `universityproject_static_data` (/app/staticfiles).
- Compose `env_file: .env` + explicit `environment:` overrides.
- `web` service runs migrations automatically on container start (that is why
  `docker compose exec web python web/manage.py migrate` often reports
  "No migrations to apply" seconds after boot).
- Volume reset wipes the DB **including the admin superuser** — seed recreates
  it from `SEED_ADMIN_USERNAME`/`SEED_ADMIN_PASSWORD` (see §5).

---

## 3. Milestone status

| Milestone | Status |
|---|---|
| M1 — Docker skeleton & scaffolding | DONE (main) |
| M2 — Django apps, models, migrations, admin, `seed_demo` | DONE |
| M3 — Real aiogram bot, /start, main menu, /settings, locale `t(lang,key)`, BlockedUserMiddleware, `PhoneNumberField` on Handover | DONE |
| M4 — FSM wizards, browse/recent, "this is mine", cancel, MatchSuggestion (user-created) | DONE |
| M4 feedback cycles | DONE: UI string fixes; **reference data is fully trilingual**; reports have trilingual titles; **mid-wizard language switch (option A)**; seed cross-day idempotency fix |
| **M5 — Django staff WMS** (claims/registration UI for StoredItem, Handover registration, protected media serving, ItemStatusLog, proper office auth) | **NEXT — not started. Do not start without explicit "proceed"** |
| M6+ — matching engine (word-overlap scoring between Lost & Found, per spec placeholder), retention/expiry worker jobs, digests | PENDING |

---

## 4. Data model & i18n scheme (current state)

### Reference data (app `catalog`) — trilingual, **uz is canonical**
- `Category`: `name_uz` (unique, NOT NULL), `name_en`, `name_ru` (blank=True),
  `emoji`, `retention_days`. Abstract base `TranslatableName` provides
  `localized_name(lang)` (fallback chain `name_{lang}` → `name_uz`).
- `Color`: same, max_length=32.
- `Location`: `building_uz` (canonical), `building_en/ru` (blank),
  `area_uz` (canonical, unique with building_uz as pair), `area_en/ru` (blank).
  Helpers: `localized_building(lang)`, `localized_area(lang)`, `display(lang)`
  (`"building — area"`), `__str__` uses display("uz").
- Saving **any** of the three models triggers auto-translation of blank
  translation columns (see §6).
- Migrations: `web/catalog/migrations/0002...` (adds uz/ru columns to the old
  English-base schema), **`0003_rename_to_uz_canonical`** — hand-written,
  RENAMES old English `name`/`building`/`area` columns into the `*_en` slots
  (no data loss), makes `*_uz` canonical, drops old `unique_building_area`,
  adds `unique_building_area_uz`, updates Meta orderings.
  **Hold the invariant: `python manage.py makemigrations --check` must stay
  "No changes detected"** — the manual migration matches the models exactly.

### User reports (app `reports`)
- `LostReport` / `FoundReport` share abstract `ReportInternals`:
  - `title` = **original as entered by the reporter (source of truth)**.
    The user's chosen bot language is the data-entry language: on every save,
    `title_{reporter.language}` is synced from `title` and the remaining
    blank streams (`title_uz/en/ru`, all blank=True) are auto-translated.
    Staff edits to `title_*` are preserved (only blank fields autofill).
  - `title_in(lang)` helper: `title_{lang}` → falls back to `title`.
  - `description = TextField()` — single field, **deliberately NOT
    translated** (free text, translator quality/limits); may be revisited later.
- Bot browse/lists (`bot/browse.py`, `bot/keyboards.py`) render
  `title_in(lang)` and `location.display(lang)`.
- `FoundReport.location` is PROTECT, `LostReport.location` SET_NULL.
- Admin: trilingual title search.

### Other apps
- `storage`: `StoredItem` (photo→`stored_items/%Y/%m/`, `shelf_code`,
  `retention_until`, FKs to Category/Color/FoundReport/User), `ItemStatusLog`.
- `matching`: `MatchSuggestion` (`suggested/reviewed_accepted/rejected`,
  `created_by` user/system, unique lost+stored constraint), `Handover`
  (`PhoneNumberField` from django-phonenumber-field, one-to-one StoredItem).
- `bot_app`: `TelegramUser` (telegram_id unique, `language`, `is_blocked`,
  `display_name`).
- Seed reference rows: 3 buildings / 20 areas, 9 categories (documents 180d,
  keys 45, electronics 90, clothing 30, bags 60, bottles 30, books 90,
  jewellery 60, other 30), 12 colors — all with uz+ru+en names.
- Seed users/rows: 30 TelegramUsers (uz/ru/en cycle), 4 office staff +
  1 superuser, 40 lost / 30 found reports, 25 stored items.

---

## 5. `seed_demo` (management command, idempotent)

- `web/catalog/management/commands/seed_demo.py`. `random.seed(42)` ⇒ fully
  deterministic output. Second run must print
  `Created in this run: lost=0 found=0 items=0`.
- **Natural keys (do not change silently):**
  - Locations: `(building_uz, area_uz)`; Categories/Colors: `name_uz`;
    all get_or_create defaults write uz+ru+en explicitly; existing rows are
    re-synced via `.update()` (update() bypasses save() → no network).
  - **Lost/Found reports: `(reporter, category, title)`** — deliberately
    WITHOUT the date. Earlier the date was part of the key and re-seeding on a
    later day silently created duplicates (absolute `date_lost` shifts with
    "today"). `date_lost/date_found` now live in `defaults` (deterministic
    spread over the last ~59 days relative to the run day).
- `TITLES` dict is keyed by **uz category names** (`category.name_uz`).
- Report seeding is wrapped in `catalog.translation.disabled()` so bulk seed
  never fires per-row online translation requests (title streams stay blank;
  display falls back to `title`).
- Superuser: created from env `SEED_ADMIN_USERNAME` / `SEED_ADMIN_PASSWORD`
  (both currently set in `.env`: username `admin`, dev password
  `admin-office-2026` — user should change for production). Existing
  password is never overwritten on re-run.
- **Known cleanup note:** a junk superuser named `1` appeared in the container
  DB once (from /admin login attempts); it was deleted. Watch for it.

---

## 6. Auto-translation service

`web/catalog/translation.py` — shared by catalog models and reports.

- Provider: **deep-translator / MyMemoryTranslator**, keyless.
  `PROVIDER_LANGS = {"uz": "uzbek", "en": "english", "ru": "russian"}`.
  ⚠️ GoogleTranslator got HTTP 429 from the containers — use MyMemory.
  Output is sanitized to its first line (`_clean`) because MyMemory sometimes
  appends junk lines.
- `translate(text, target_lang, source_lang="uz")` → `""` on ANY failure
  (offline, rate limit, disabled) — never raises.
- `_auto_translate_enabled()` checks `settings.AUTO_TRANSLATE` **and** the
  module-level `_DISABLE_DEPTH`. `AUTO_TRANSLATE` is an env-driven Django
  setting (`.env.example`: `AUTO_TRANSLATE=True`).
- `disabled()` context manager — disables translation (used by seed).
- `auto_fill(fields_map, source_lang=None)` — fills blank values by
  translating the first non-empty one (or the forced `source_lang` value);
  mutates `fields_map` in place.
- `apply_to_fields(obj, base_fields)` — for each base ("name", "building",
  "area"...) builds a `{uz,en,ru}` map from `obj`, runs `auto_fill`, writes
  back only changed values. Called from `Category/Color.save()` (via
  `_autofill_name`) and `Location.save()` (building + area separately).
- Reports call `auto_fill(fields_map, source_lang=reporter.language)` inside
  `_sync_translated_title()` on every save.

---

## 7. Bot behaviour (aiogram 3.x)

- All user-visible strings live ONLY in `bot/strings.py` via `t(lang, key)`
  (uz default, ru, en). Languages: `SUPPORTED_LANGUAGES = ("en", "ru", "uz")`.
- **Language = data-entry discipline (user-confirmed):** the language chosen in
  `/settings` is persisted to `TelegramUser.language` and drives everything
  for that user: menus, prompts, localized reference names, and the report
  entry language.
- **Mid-wizard language switch — "option A" (user-confirmed):**
  `/settings` and `setlang:*` **do NOT clear FSM state**. If a wizard is
  active, `wizards.resume_after_language_change()` maps the active state
  string (format `"LostWizard:title"`, `"FoundWizard:summary"` etc.) and
  re-renders the SAME step in the new language; typed texts are NOT re-asked.
  `_refresh_labels()` recomputes stale pick-time labels
  (`category_label/color_label/location_label/building_label`) from stored IDs
  using the current language, before every prompt and the summary.
  Hint string `settings_wizard_hint` (3 langs) explains this in-app.
- ⚠️ **aiogram gotcha:** `str(LostWizard.title)` returns
  `"<State 'LostWizard:title'>"` — never compare `str(State)` with the storage
  state string; compare `f"{group.__name__}:{field}"` instead (as
  `_locate_wizard_state` does now).
- Router registration order in `bot/main.py`: `handlers.router` →
  `wizards.router` → `browse.router` → `handlers.fallback_router`.
  `NO_COMMAND_TEXT = ~F.text.startswith("/")` keeps commands reachable in FSM
  states. FSM states: `bot/states.py` (LostWizard, FoundWizard incl.
  category→title→description→color→building→area→date→photo(+custody→consent
  for found)→summary; edit-mode jumps via `_advance`).
- Inline callback data prefixes (see `bot/keyboards.py`): `setcat:`, `setcol:`,
  `setbld:`, `setarea:` (0 = "no area", allowed for lost), `wiz_edit`,
  `editf:<field>`, `wiz_confirm`, `skippic`, `custody:*`, `consent:*`,
  `recent:<page>`, `mine:<found_id>`, `minepick:*`, `cnl:lost|found:<id>`,
  `setlang:`, reply-keyboard texts match `menu_lost/menu_found/menu_recent/
  menu_my_reports` strings per language.
- `fetch_buildings(lang)` in `bot/wizards.py` returns ordered
  `(building_uz_key, localized_display)` pairs; areas are fetched by
  `building_uz` key; wizard stores `building_label` too.
- Middleware: `bot/middlewares.py` `BlockedUserMiddleware` (outer,
  auto-creates TelegramUser, sets `is_new_user`, aborts politely for blocked
  users).

---

## 8. Verification recipes (run these before reporting a milestone)

Local (host): `python -X utf8 web/manage.py check`,
`python -X utf8 web/manage.py makemigrations --check --dry-run`
(must be "No changes detected"), `python -X utf8 web/manage.py seed_demo`
twice (2nd run must create 0 rows).

Containers: `docker compose up -d --build` (rebuild is REQUIRED after code
edits — plain `up -d` / `--force-recreate` reuse the old image and have caused
"my fix isn't there" loops), then `docker compose exec web python
web/manage.py seed_demo`.

FSM integration test (mirrors M4 end-to-end without Telegram): copy
`%TEMP%\test_fsm.py` into the bot container and run:

```powershell
docker cp "$env:TEMP\test_fsm.py" lnf_bot:/tmp/test_fsm.py
docker compose exec -T -e PYTHONPATH=/app bot python /tmp/test_fsm.py
```

It must print ALL sections OK, ending with
`== MID-WIZARD LANGUAGE SWITCH ==` ... `report created with entry language
Russian (title_ru=source, uz/en auto): OK`. The test:
- runs full lost+2×found wizards (photo file_id, custody, consent),
- recent-item feed, "this is mine" suggestion + duplicate guard,
- cancel report,
- uz→ru switch mid-wizard (`/settings` → `setlang:ru`): asserts the title
  step is re-prompted in Russian (`"Короткое название"` appears in sent
  messages), the FSM state survives, and the created report has
  `title_ru == "Красный рюкзак"` with `title_uz`/`title_en` auto-filled.
The test cleans up after itself (users TG_ID and TG_ID+1).

Other temp debug/check scripts (rebuildable from this doc if lost):
`check_i18n.py`, `check_kb.py` (localized keyboard rendering),
`check_translate.py`/`check_translate2.py` (catalog auto-translation online +
offline), `check_titles.py`/`check_titles_db.py` (report title streams),
`dbg_state.py`/`dbg_state2.py` (FSM state tracing via outer middleware).
All are run the same way: copy to `/tmp/` in `lnf_bot`, run
`docker compose exec -T -e PYTHONPATH=/app bot python /tmp/<script>.py`.

---

## 9. Known pitfalls / gotchas

1. **Never rewrite PowerShell files via inline `Get-Content | Set-Content`
   through emoji content** — it has mangled emoji in `bot/keyboards.py`
   before. Use the edit/write file tools instead.
2. Docker daemon sometimes stops: start Docker Desktop, poll `docker info`.
3. Path contains a space: always quote ("C:\projects\university project").
4. `.env` holds the real bot token +	admin creds — never commit, never leak
   into reports/summaries. `.env.example` is the safe template.
5. `docker compose up -d` without `--build` silently runs stale code.
6. Local host DB lives at `web/db.sqlite3` (gitignored); the container uses
   `/app/data/db.sqlite3` (volume). Local and container DBs diverge — the
   container is the source of truth for bot verification. Do not reset the
   volume without need (see §5 superuser note).
7. MyMemory rate limits exist; the graceful-degradation contract is:
   blank translations stay blank, staff fill manually. Never fail hard.
8. Seed titles/randomness are deterministic — keep `random.seed(42)` and the
   natural keys stable, or expect duplicate/missing demo rows.
9. `ItemStatusLog`, `MatchSuggestion`, `Handover` flows are NOT yet wired into
   bot/web (they are M5/M6 scope); don't assume they have live entry points.

---

## 10. Next move (M5 — only after the user says "Proceed to Milestone 5")

Per the user's Section-3 spec, Milestone 5 = Django custom staff interface:
- Claims/registration UI for StoredItem (create stored item from a found
  report, generate `shelf_code`, photo upload, `retention_until` from category
  `retention_days`).
- Handover registration connected to `MatchSuggestion` approval.
- Protected media serving (photos are not public; staff/auth-gated).
- `ItemStatusLog` entries on status changes.
- Real auth for office staff (currently /admin relies on standard Django
  auth; `ALLOWED_HOSTS` trick noted in earlier context needs replacement).
- Remember: `web/config/urls.py` has TODO placeholders for page-level
  `@login_required` staff gating.

Present the M5 plan → implement → verify (docker rebuild + seed idempotency +
targeted checks) → milestone report with commit message → WAIT for the user.

---

## 11. File inventory (repo root relative)

| Path | Role |
|---|---|
| `docker-compose.yml`, `Dockerfile`, `.env.example`, `.dockerignore`, `.gitignore` | infra (M1) |
| `.env` | REAL secrets (BOT_TOKEN, OFFICE_GROUP_ID, DJANGO_*, SEED_ADMIN_*, AUTO_TRANSLATE) — gitignored |
| `requirements.txt` | Django, aiogram, gunicorn, whitenoise, Pillow, python-dotenv, **deep-translator** |
| `web/manage.py`, `web/config/{settings,urls,wsgi,asgi}.py`, `web/config/db_hooks.py` | Django core; WAL pragmas; AUTO_TRANSLATE flag |
| `web/catalog/models.py` | trilingual reference models + TranslatableName |
| `web/catalog/translation.py` | auto-translate service |
| `web/catalog/migrations/0002...`, `0003_rename_to_uz_canonical.py` | i18n schema evolution |
| `web/catalog/admin.py` | admin list/search over `*_uz/en/ru` |
| `web/catalog/management/commands/seed_demo.py` | idempotent seeder (see §5) |
| `web/reports/models.py` | Lost/Found + trilingual title sync |
| `web/reports/admin.py` | report admin (trilingual search) |
| `web/storage/models.py`, `web/matching/models.py`, `web/bot_app/models.py` | domain models |
| `bot/main.py` | dispatcher wiring, long polling, router order |
| `bot/strings.py` | ALL bot texts (uz/ru/en) |
| `bot/handlers.py` | /start, /settings, setlang, fallback |
| `bot/wizards.py` | FSM flows, `_refresh_labels`, `resume_after_language_change` |
| `bot/browse.py`, `bot/keyboards.py`, `bot/states.py`, `bot/middlewares.py` | rest of the bot layer |
| `worker/main.py` | heartbeat loop (M7+ scope) |


