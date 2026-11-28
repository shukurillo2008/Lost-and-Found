# Demo video script (6–8 minutes)

A scene-by-scene recording plan for the Campus Lost & Found project. The
interface is available in Uzbek, Russian and English; record in the language
you will use for the defense and switch once to prove the other catalogs work.

---

## 0. Before recording

```bash
# Fresh demo data (optional: this deletes the current volumes and all data)
docker compose down -v
docker compose up -d --build
docker compose exec web python web/manage.py seed_demo

# Normal start with existing data
docker compose up -d --build
docker compose exec web python web/manage.py seed_demo
```

Checklist:

- [ ] `docker compose ps` shows `lnf_web` healthy, `lnf_bot` and `lnf_worker` up.
- [ ] Office login works: <http://localhost:8000/> with the
      `SEED_ADMIN_USERNAME` / `SEED_ADMIN_PASSWORD` values from `.env`.
- [ ] The Telegram bot `@lost_and_found_ttpu_bot` responds to `/start`.
- [ ] Two Telegram accounts are available: one reporter (lost item) and one
      finder (found item), or use one account and two reports.
- [ ] Browser zoom is 100–110%, notifications are muted, and the office UI is
      in the language you will speak.
- [ ] Close extra tabs. Keep the terminal with `docker compose logs -f worker`
      ready for the digest/worker scene.

Reset between takes:

```bash
docker compose exec web python web/manage.py seed_demo
```

`seed_demo` is idempotent: re-running it does not duplicate rows.

---

## 1. Opening — problem and architecture (0:00–0:40)

**Show:** a title slide or the README architecture diagram.

**Say:**

> This is a campus lost-and-found platform. Students report lost or found
> items in a Telegram bot, the office receives physical items into storage,
> and a matching engine proposes pairs. Everything runs as four Docker
> services on one host: Django for the office UI, an aiogram bot, a background
> worker, and Caddy for HTTPS. The same Django ORM and SQLite database are
> shared by all services.

---

## 2. Bot — report a lost item (0:40–1:40)

**Show:** Telegram, `/start`.

1. Pick a language (e.g. Uzbek) and show the main menu.
2. Tap **"Yo'qotdim" / "I lost something"**.
3. Walk the wizard: category → colour → title → description → location →
   date. Use a distinctive title such as `qora himoya g'ilofli telefon`.
4. Submit and show the confirmation with the report id.

**Say:**

> The wizard validates each step, stores the report in the reporter's
> language, and fills the other two language streams. The report starts as
> `open`.

---

## 3. Bot — report a found item with consent (1:40–2:50)

**Show:** the second account (finder), `/start` → **"Topdim" / "I found
something"**.

1. Use the **same category and colour** as the lost report, a matching title
   and location, and a found date after the loss date.
2. Choose **"Ofisga topshirdim" / "Handed to the office"**.
3. Show the contact-consent question; choose **allow** so the later match
   notification can include the finder's `@username` and phone.
4. Submit.

**Say:**

> Custody is explicit: the finder either hands the item to the office or
> keeps it. Contact details are shared with a possible owner only when the
> finder consents.

Optional: open **"Oxirgi topilmalar" / "Recent found items"** and show the
card with the **"Bu meniki!" / "This is mine"** button. Do not press it yet if
you want the worker to create the suggestion in scene 5.

---

## 4. Office — dashboard (2:50–3:25)

**Show:** <http://localhost:8000/>, log in.

- Point at the KPI cards: items in storage, open lost reports, pending
  matches, returns this month.
- Show the charts: items by category, top locations, retention outlook, and
  the 8-week received/returned/disposed flow.
- Switch the language once (UZ → RU → EN) and point out that every label
  changes.

**Say:**

> The dashboard is the office's daily overview. The numbers come from the same
> querysets as the lists and the digest, so they never disagree.

---

## 5. Office — receive the found item (3:25–4:30)

**Show:** **Receive item** (`/storage/receive/`).

1. In the **found report** selector, pick the report from scene 3.
2. Show the prefill: title, description, category and colour are filled from
   the report; the report details card shows the finder and consent.
3. Type a shelf code. Show the inline shelf check accepting
   `A-01` and rejecting a duplicate/malformed code.
4. Upload a photo (or tick **"Use the report photo"**).
5. Save. The page redirects to the new item detail.

**Say:**

> Receiving creates the physical item, computes the retention deadline from
> the category policy, writes the first status-log row, and marks the linked
> found report `registered`. Any live match for that report is re-pointed at
> the new item.

---

## 6. Worker — matching and notification (4:30–5:15)

**Show:** terminal with `docker compose logs -f worker`, or the **Match
review** page (`/reports/matches/`).

- Wait for the matching cycle (or run it manually):

  ```bash
  docker compose exec web python -c "import worker.main as w; print(w.run_matching_cycle())"
  ```

- Show the log line `system suggestion: report #… × item #… (score …)`.
- Open the lost report from the bot, or the match review queue, and point at
  the score breakdown (colour, time, building/area, shared words).
- Confirm the suggestion.

**Show:** the reporter's Telegram — the match notification with the finder's
`@username` and phone (because consent was given).

**Say:**

> The worker only suggests pairs scoring above 5; a human always confirms.
> The same scoring function is used by the worker, the office and the bot, so
> one weight change re-scores everything consistently.

---

## 7. Office — handover (5:15–6:05)

**Show:** the item detail → **Return**.

1. Point at the status history and the match block.
2. Open the handover form: the receiver is prefilled from the confirmed lost
   claim (never from the finder).
3. Enter the receiver's name and the last four digits of their ID; add a note.
4. Submit.

**Show:** the item becomes `returned`, the status log has a new row, and the
linked found/lost reports are closed. The reporter receives the handover
notification.

**Say:**

> A return always records who took the item. The ID digits live only in the
> confidential handover record; they never appear in the item or the audit
> log.

---

## 8. Office — kept-by-finder and reference data (6:05–6:50)

**Show:** **Reports → Found reports** (`/reports/found/`).

- Filter by custody `Kept by finder`.
- Point at the consent badge and the **"Mark as handed to office"** button on
  an open kept row. Click it and show the row moving to `handed_to_office`,
  ready for the receive flow.

**Show:** **Catalog → Categories** (`/catalog/categories/`).

- Add a category (e.g. `Sinov kategoriyasi`, retention 45 days) and show it in
  the list and in the receive dropdown.
- Point out the delete guard on locations/categories that are referenced by
  reports.

---

## 9. CSV and daily digest (6:50–7:30)

**Show:** **Storage inventory** → **Export CSV**.

- Open the downloaded file and point at the localized headers, the local
  `Received date`, and the status-aware rows.

**Show:** the office Telegram group or a preview of the digest:

```bash
docker compose exec web python -c "from bot_app.digest import build_digest; t, c = build_digest(); print(t); print(c)"
```

**Say:**

> The digest is sent once per local day at 09:00 Asia/Tashkent, is idempotent
> per date, retries safely, and stays under Telegram's 4096-character limit.

---

## 10. Tests and close (7:30–8:00)

**Show:** terminal.

```bash
docker compose exec -T -e DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,web,testserver \
  web python web/manage.py test catalog matching storage bot_app reports
```

**Say:**

> 118 automated tests cover scoring, state transitions, privacy, expiry,
> digest idempotency, CSV export and the office pages. The project is
> containerized, documented in the README, and ready to deploy behind the
> included Caddy HTTPS overlay.

**Close:** one sentence on what you would build next (QR shelf labels, public
search, CI).

---

## Recording tips

- Record at 1080p, 30 fps; use a large cursor and keep the pointer still while
  speaking.
- Cut dead time between wizard steps; keep each scene under 90 seconds.
- If the bot notification does not arrive during the take, show the
  `docker compose logs -f web` line and continue — do not restart the demo.
- Keep a second terminal ready with the test command so the final scene never
  waits for discovery.
