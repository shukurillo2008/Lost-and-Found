LOST and FOUND


### Milestone 1: Docker Compose Skeleton & Project Scaffolding
* Configure root layout with `web/`, `bot/`, and `worker/` directories[cite: 2].
* Provide `.env.example` with required runtime variables[cite: 6].
* Write `Dockerfile` definitions (Python 3.11+) and `docker-compose.yml` linking `web`, `bot`, and `worker` to a shared named volume mounted at `/app/data/` for SQLite and `/app/media/` for files[cite: 2, 6].
* Initialize Django project with SQLite WAL mode pragma configuration.
* **Stop Criteria**: `docker compose up --build` starts all services cleanly without restart loops[cite: 6].

### Milestone 2: Reference Models, Core Models, Seed Data & Admin
* Implement all models in Section 2 with complete migrations[cite: 2, 3].
* Implement `retention_until` auto-calculation in `StoredItem.save()`[cite: 2, 3].
* Create management command `python manage.py seed_demo` generating[cite: 6]:
  * 3 buildings, 20 areas, 9 categories (with retention days), 12 colors[cite: 6].
  * 30 users, 40 lost reports, 30 found reports, 25 stored items with realistic dates across two months[cite: 6].
* Configure Django Admin for all models with filters, search, and list displays[cite: 4].
* **Stop Criteria**: Migrations apply; `seed_demo` runs idempotently; Django Admin is fully functional[cite: 4, 6].

### Milestone 3: Telegram Bot Core, i18n & User Middleware
* Initialize `aiogram 3.x` bot with `django.setup()` in its process[cite: 2, 6].
* Create `bot/strings.py` supporting Uzbek (Latin, default), Russian, and English[cite: 3, 6]. No strings in handlers[cite: 3].
* Implement `/start` handler: auto-create `TelegramUser`, language selection if new, main menu (I lost something / I found something / Recent found items / My reports)[cite: 3, 4].
* Implement `/settings` handler: language switcher updating `TelegramUser.language`[cite: 3, 4].
* Implement `BlockedUserMiddleware` returning a single polite message if `is_blocked=True`[cite: 3, 4].
* **Stop Criteria**: Bot runs in container, handles `/start`, switches languages, and blocks banned users[cite: 3, 4].

### Milestone 4: Bot Intake Wizards (FSM) & Self-Service
* **Lost Wizard**: Category (inline keyboard with emojis) $\rightarrow$ Title $\rightarrow$ Description $\rightarrow$ Color $\rightarrow$ Location (Building $\rightarrow$ Area cascading keyboard) $\rightarrow$ Date lost $\rightarrow$ Optional photo $\rightarrow$ Summary with Confirm/Edit/Cancel[cite: 4].
* **Found Wizard**: Same flow + custody branch ("Handed to office" vs. "I still have it") + explicit finder contact share consent[cite: 4, 5].
* **Recent Found Items**: Paginated cards (photo, category, title, location, date) found within the last 30 days[cite: 4]. Each card includes a "This is mine" button creating a user `MatchSuggestion`[cite: 4].
* **My Reports**: Lists user's lost and found reports with statuses; provides a button to cancel open reports[cite: 4].
* **Stop Criteria**: Complete FSM flows write valid records to database; photo uploads save Telegram `file_id`[cite: 3, 4].

### Milestone 5: Django Custom Staff Interface (WMS)
* Build custom Django views (staff login required, styled cleanly)[cite: 4]:
  1. `Receive Item`: Desk intake form. Search and link existing `FoundReport` or create blank; auto-suggest next available shelf code; photo upload; save creates `StoredItem` and sets linked `FoundReport.status = 'registered'`[cite: 3, 4].
  2. `Storage List & Detail`: Filter by category, shelf, received date, expiring within 7 days; detail view with photo, timeline log, and action buttons[cite: 4].
  3. `Handover Modal / Form`: Receiver name, last 4 digits of ID, staff signature, notes. Atomically sets `StoredItem.status = 'returned'`, updates linked `LostReport.status = 'returned'`, creates `Handover` record, and triggers bot notification to reporter[cite: 3, 4, 5].
  4. `Reference Data Pages`: Create/edit views for campus locations and categories[cite: 4].
* **Stop Criteria**: Staff can perform intake, storage audit, and handover workflows end-to-end[cite: 4].

### Milestone 6: Heuristic Matching Scoring Engine & Tests
* Implement `matching/engine.py` adhering strictly to the scoring rules in Section 3[cite: 5].
* Write Django unit tests in `matching/tests.py` verifying[cite: 6]:
  * Category mismatch returns score 0[cite: 5, 6].
  * Color match adds exactly 3 points[cite: 5].
  * Temporal match adds 2 points (and 0 if date lost > date found)[cite: 5].
  * Location match adds 2 for building and 3 for building + area[cite: 5].
  * Word overlap correctly tokenizes, removes stop words, and caps at 4 points[cite: 5, 6].
  * Boundary scores verify threshold trigger ($> 5$)[cite: 5].
* **Stop Criteria**: All matching unit tests pass with 100% assertions green[cite: 6].

### Milestone 7: Background Worker Service & Notification Lifecycle
* Configure asynchronous scheduler loop in `worker/` process[cite: 2].
* **10-minute Match Run**:
  * Computes scores for open `LostReport` against active `StoredItem` records[cite: 5].
  * For score $> 5$, creates `MatchSuggestion` and sends Telegram notification to reporter: *"An item similar to your lost [title] was handed to the office. Come to room 104 with your ID."* with "Yes, that's mine" / "No" buttons[cite: 4, 5].
  * **Guaranteed Deduplication**: Use database uniqueness and existence checks to ensure no duplicate suggestion is ever created, even across process restarts[cite: 5, 6].
* **Retention Reminders**: Flag items within 7 days of `retention_until` for daily digest; items past retention become flagged as "ready for disposal" (status changed only by staff, never automatically)[cite: 5].
* **Lost Report Auto-Expiry**: Move open `LostReport` records older than 90 days to `expired`; notify reporter with one-tap reopen button[cite: 5].
* **Daily Office Digest**: Broadcast daily at 09:00 (Asia/Tashkent) to the office Telegram group summarizing storage counts, expiring items, and pending matches[cite: 5].
* **Stop Criteria**: Worker executes all loops without DB lock collisions; duplicate prevention tests pass[cite: 5, 6].

### Milestone 8: Dashboard Analytics, Charts & CSV Export
* **Dashboard View**:
  * Metrics counters: Items in storage, items expiring in $\le$ 7 days, open lost reports, pending match suggestions, items returned this month[cite: 4].
  * Chart.js visualizations: Distribution of items by category, and top 10 lost report locations[cite: 4, 6].
* **Inventory Export**: View generating a CSV download of currently stored items for physical inventory checks[cite: 4, 5].
* **Protected Media Endpoint**: Serve uploaded images only after verifying request user has `is_staff=True`[cite: 5].
* **Documentation**: Generate complete `README.md` with setup guide, Mermaid entity relationship diagram, matching logic breakdown, and privacy notes[cite: 7].
* **Stop Criteria**: Dashboard renders Chart.js charts cleanly; CSV downloads correctly; non-staff cannot access media files[cite: 4, 5, 6].

### Milestone 9: Bonus Features & Final Hardening (For Cum Laude / 30+)
* **QR Shelf Labels**: PDF generation view creating printable QR code labels containing shelf code and direct link to item detail page[cite: 7].
* **Public Catalog View**: Read-only, unauthenticated web list of recently found items (excluding personal contacts and private finder details) embeddable in the university portal[cite: 7].
* **GitHub Actions CI**: Workflow running flake8/black linters and `python manage.py test` on push[cite: 7].
* **Comprehensive Test Suite**: Execute full test suite covering status transitions, deduplication, retention calculation, and handover workflows[cite: 6].
* **Stop Criteria**: All tests pass; CI workflow is green; printable QR labels generate valid PDFs[cite: 6, 7].

---
