# Defense notes

A compact map of the project for the oral defense: the pitch, architecture,
requirement coverage, design decisions, likely questions and a live-change
rehearsal.

---

## 1. One-minute pitch

> Campus Lost & Found is a three-service platform for a university office.
> Students use a Telegram bot in Uzbek, Russian or English to report lost and
> found items. The bot stores structured reports in Django; a background
> worker scores every open lost report against every item in storage and
> proposes matches. Office staff review those matches in a Django web panel,
> receive physical items onto shelves, record the handover to the owner, and
> manage reference data. A daily digest goes to the staff Telegram group.
> Everything runs with Docker Compose, shares one SQLite database, and is
> covered by 118 automated tests.

---

## 2. Architecture

```text
Telegram user
    │
    ▼
aiogram bot (lnf_bot) ── Django ORM ──┐
                                      │
Django office UI (lnf_web, gunicorn) ─┼── SQLite (WAL) + media volume
                                      │
worker (lnf_worker) ── Django ORM ────┘
    │
    └── Telegram Bot API (notifications, digest)

Caddy (deploy overlay) ── HTTPS ──> lnf_web:8000
```

- **One Django settings module** (`web/config/settings.py`) is imported by all
  three Python services, so the schema, timezone, translation settings and
  Telegram client are identical everywhere.
- **No message queue.** The worker is a timed loop; the bot and web write to
  the same database. This is deliberate for a single-host university
  deployment.
- **SQLite in WAL mode** with a busy timeout and `IMMEDIATE` transactions.
  Writes from the bot, web and worker do not block each other indefinitely.

---

## 3. Requirement coverage

| Area | Where it lives | What to show |
| --- | --- | --- |
| Telegram reporting | `bot/wizards.py`, `bot/handlers.py` | `/start`, lost/found wizards, validation, language switch |
| Found-item browsing | `bot/browse.py` | recent items, pagination, "this is mine" suggestion |
| Notifications | `web/bot_app/notifications.py` | match confirmed, handover, expiry + reopen |
| Office dashboard | `web/office/views.py::dashboard_page` | KPI cards, four charts |
| Storage workflow | `web/office/views.py::storage_receive`, `storage_item_detail`, `storage_handover` | receive with prefill, shelf check, photo, status log, return/dispose/transfer |
| Matching | `web/matching/engine.py`, `services.py` | score breakdown, threshold, confirm/reject, one confirmed match per report |
| Reports | `web/office/views.py::reports_lost_*`, `reports_found_list` | filters, detail, review queue, kept-by-finder custody |
| Reference data | `web/office/views.py::catalog_*` | trilingual categories, colours, locations; delete guards |
| Worker | `worker/main.py` | retention flags, 90-day expiry, matching, digest |
| Digest | `web/bot_app/digest.py` | daily message, per-date idempotency, retry policy, 4096 cap |
| Export | `web/office/views.py::storage_export_csv` | status-aware monthly CSV, local dates |
| Deployment | `deploy/` | Caddy HTTPS overlay, secure cookies, HSTS, CSRF origins |
| Tests | `web/*/tests.py` | 118 tests, command in the README |

---

## 4. Design decisions and trade-offs

### Why SQLite?

A university office has one host, a small dataset and low write volume. SQLite
removes a service to operate and back up, and WAL mode handles the three
writers. The trade-off is no horizontal scaling; PostgreSQL is the migration
path if the project grows (Django's ORM makes the switch mostly a settings
change).

### Why a heuristic engine, not machine learning?

The course asks for explainable matching. Every suggestion stores its
breakdown (colour, time, building/area, shared words), so staff can see why a
pair scored what it scored. Weights are constants in one file; changing one
number re-scores the whole system consistently. Category is a hard gate: a
wallet never matches a jacket.

### Why does a human confirm every match?

False positives are expensive (handing an item to the wrong person). The
worker only *suggests*; staff confirm. Confirming one suggestion auto-rejects
competing rows and a partial unique constraint guarantees one confirmed match
per lost report even under concurrent requests.

### How is privacy protected?

- The finder chooses whether contact details may be shared. The confirmed
  match notification includes `@username` and phone only when consent is
  `True`; otherwise the reporter is told to contact the office.
- The handover stores only the last four digits of the receiver's ID, in the
  confidential `Handover` row. Those digits never enter the item, the status
  log or the reports.
- Staff pages are gated by login **and** `is_staff`; every state-changing form
  is CSRF-protected.

### Why are there no Django forms?

The office UI brief constrains the stack to Bootstrap, jQuery and Select2 and
asks for hand-built pages. Validation therefore lives in the views, with
field-keyed errors, an error summary and server-side re-checks (shelf regex,
duplicate shelf, required fields, photo MIME/size). The trade-off is more
explicit code; the benefit is full control over the markup and the Uzbek
copy.

### How are the three languages kept consistent?

Reports store the canonical `title`/`description` plus `_uz`, `_en`, `_ru`
streams. On creation, the reporter's language stream is set and the other two
are auto-translated when `AUTO_TRANSLATE` is on. On later saves, the streams
are re-synced **only** when the canonical text changed — otherwise switching
the reporter's language would overwrite a correct translation. Office UI
strings use gettext catalogs (`web/locale/uz`, `ru`).

### Why does the digest have its own retry state?

`DigestRun.sent_on` is unique, so a restart cannot send twice. A failed send
increments `attempts`, waits `DIGEST_RETRY_MINUTES`, and gives up after five
attempts for that day. This prevents a bad chat id from hammering the Bot API
every heartbeat. The text is capped below 4096 UTF-16 units at whole-line
boundaries so HTML tags are never split.

---

## 5. Q&A bank

**Q: How does the matching score work?**
A: Category must be identical, otherwise the pair scores 0. Then +3 for the
same colour, +2 when the found date is at or after the loss date and within
14 days, +2 for the same building (+1 more for the same area), and +1 per
shared word in title/description, capped at +4. The worker only creates a
suggestion when the total is strictly greater than 5.

**Q: Why does the digest job run on every heartbeat if it sends once a day?**
A: The `DigestRun` row is the idempotency guard, so a tick before the digest
hour or after a successful send is a cheap no-op. Running it every 30 seconds
means a restart at 09:05 still delivers the digest, and a failed send retries
on the next tick without a separate scheduler.

**Q: What happens if two staff confirm different suggestions for the same
lost report at the same time?**
A: `apply_decision` runs in a transaction, rejects every competing
suggested/confirmed row, then confirms the chosen one. A partial unique index
(`unique_confirmed_suggestion_per_report`) is the database backstop; the
second transaction cannot leave two confirmed rows.

**Q: What if the finder keeps the item instead of handing it in?**
A: The found report is `kept_by_finder`. If the finder later brings it in,
staff press **Mark as handed to office** on the found-report table. The report
then appears in the receive selector; receiving re-points live matches at the
new stored item. The finder is never prefilled as the receiver.

**Q: How do you avoid duplicate suggestions?**
A: `(lost_report, stored_item)` is unique. The worker also tracks the found
report behind each item, so a "this is mine" suggestion is not duplicated
once the item is received. User suggestions check the found report before
creating a row.

**Q: What happens when a report expires?**
A: After 90 days an open report becomes `expired`, its pending suggestions are
rejected, and the reporter gets a one-tap reopen button. Reopening writes
`reopened_at`, restarting the clock. Decisions on closed reports are refused.

**Q: How does the handover find the claimant?**
A: It looks for a confirmed suggestion on the item. If the confirmation came
from a found-report-only suggestion, `apply_decision` resolves and attaches
the linked stored item first, so the handover still finds the claim.

**Q: What if an item is deleted from the database?**
A: A `pre_delete` signal removes suggestions that point only at that item
(otherwise the `SET_NULL` would violate the source check), keeps suggestions
that also carry a found report, and reopens a matched report that lost its
confirmed match.

**Q: Why last four digits, not the full ID?**
A: The handover needs a verifiable proof of identity, not a copy of the
document. Four digits are enough to match the physical ID at the counter and
limit the damage of a database leak. The value is stored only in `Handover`
and excluded from logs.

**Q: How do you test Telegram without spamming users?**
A: Tests patch `telegram_api.send_message`; the client returns `None` on
failure and callers treat it as a no-op. Seeded users have fake ids, so live
runs log a rejected send without breaking the cycle.

**Q: Why does the worker use `asyncio.to_thread`?**
A: Django's ORM is synchronous. The worker's outer loop is async for the
sleep/heartbeat, but each work cycle runs in a thread so the ORM does not
block the event loop.

**Q: How is the CSV month calculated?**
A: A local-time range `[first of month, first of next month)` in
`Asia/Tashkent`, and the `Received date` cell is converted with
`timezone.localtime`. An item received at 20:00 UTC on 31 May appears in June
as `01.06.2026`.

**Q: What about a malformed month or status parameter?**
A: Both fall back safely: invalid status → `in_storage`; malformed month →
current month. The export link carries the active list filter.

**Q: How would you scale this?**
A: PostgreSQL, object storage for photos, a real queue (Celery/RQ) for
matching and notifications, and multiple web workers behind the proxy. The
matching engine and services are already separated from the views, so the
move is incremental.

**Q: What would you improve next?**
A: QR shelf labels, a public found-item search page, CI, digest localization
for staff language, and rate limiting on the bot.

**Q: Is the site deployed?**
A: The production overlay is included (`deploy/docker-compose.prod.yml`,
`deploy/Caddyfile`) with secure cookies, HSTS, CSRF origins and a
proxy-trusted `X-Forwarded-Proto`. The public URL is recorded in the README
once the host is provisioned.

---

## 6. Live-change rehearsal

Practise these three changes; each takes under two minutes.

### A. Add a category (no code)

1. Open **Catalog → Categories**.
2. Enter `Sinov kategoriyasi`, retention `45`, save.
3. Show it in the list and in the **Receive item** category dropdown.
4. Point out that the category cannot be deleted while reports/items use it.

### B. Change a matching weight (code)

`web/matching/engine.py`:

```python
WEIGHT_COLOR = 3          # change to 4
MIN_SYSTEM_SCORE = 5      # or raise the threshold
```

Rebuild/restart the service that uses it (code is baked into the image):

```bash
docker compose up -d --build web worker bot
```

Show the effect with a shell snippet or the review page's score breakdown.
Revert afterwards. Mention that the unit tests pin the current weights, so a
real change also updates their expected scores — that is intentional, not a
failure.

### C. Add a small filter (code)

In `web/office/views.py::storage_item_list`, add an "overdue only" preset:

```python
overdue_on = bool(request.GET.get("overdue"))
...
if overdue_on:
    items = items.filter(retention_until__lt=today)
```

Add it to `has_filters`, pass it in the context, and add a checkbox/link in
`web/templates/storage/item_list.html`:

```html
<a class="btn btn-sm btn-outline-danger"
   href="?overdue=1">Overdue only</a>
```

Run the storage tests and show the filtered list. The same pattern is how the
existing status/date/shelf filters are built.

---

## 7. Demo failure fallbacks

- **Bot does not answer:** show `docker compose logs --tail=30 bot`; the token
  or long-polling conflict is visible there. Continue with the office scenes.
- **No match suggestion yet:** run the worker cycle manually (command in the
  demo script) instead of waiting for the interval.
- **Notification does not arrive:** show the send log line and the seeded
  data; do not restart the demo.
- **Photo upload fails:** the form shows a field error; demonstrate the
  validation instead of retrying blindly.
- **Database was reset:** `docker compose exec web python web/manage.py
  seed_demo` restores the demo dataset idempotently.

---

## 8. Numbers to remember

- 4 containers in production: web, bot, worker, Caddy.
- 3 languages: Uzbek (default), Russian, English.
- 5 scoring criteria: category gate, colour, time window, building/area,
  shared words.
- Threshold: suggestions only when score > 5.
- Retention: category-defined days; digest warns 7 days ahead.
- Report expiry: 90 days, with a bot reopen button.
- Tests: 118, run with the command in the README.
