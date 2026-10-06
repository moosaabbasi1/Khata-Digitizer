# Khata Digitizer & Micro-Credit Scorer

Phase 1: Environment Setup & Database Connection

## What's in this phase

- Django project `khata_project` + app `khata_app` created
- `settings.py` configured![alt text](image.png) to connect to MS SQL Server via `mssql-django`
- Secrets/DB credentials moved out of code and into `.env` (via `python-decouple`)
- Static file and media file (uploaded chit images) configuration in place
- `TIME_ZONE` set to `Asia/Karachi`

## Fedora setup (run this on your dev machine)

Django + `pyodbc` need the Microsoft ODBC Driver for SQL Server installed at
the OS level — `pip install` alone isn't enough.

```bash
# 1. Add the Microsoft package repo
sudo dnf install -y https://packages.microsoft.com/config/rhel/9/packages-microsoft-prod.rpm

# 2. Install the ODBC driver + tools + unixODBC headers
sudo dnf install -y unixODBC-devel
sudo ACCEPT_EULA=Y dnf install -y msodbcsql18 mssql-tools18

# 3. (optional) add sqlcmd/bcp to your PATH
echo 'export PATH="$PATH:/opt/mssql-tools18/bin"' >> ~/.bashrc
source ~/.bashrc

# 4. Confirm the driver registered correctly
odbcinst -q -d
# should list: [ODBC Driver 18 for SQL Server]
```

If you're pointing at SQL Server running in Docker instead of a bare-metal
install, none of the above is needed on the *server* side — only the client
driver above needs to be on the machine running Django.

## Project setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# now edit .env with your real DB_NAME / DB_USER / DB_PASSWORD
```

## Verification steps for Phase 1

```bash
# 1. Confirm Django can import the mssql backend and reach the server
python manage.py check --database default

# 2. Run the built-in migrations against MSSQL
python manage.py migrate

# 3. Create an admin user and start the dev server
python manage.py createsuperuser
python manage.py runserver
```

If `migrate` completes without errors and you can log into
`http://127.0.0.1:8000/admin/`, the MSSQL connection is confirmed and Phase 1
is done.

### Common connection issues

- **`Login failed for user`** — check `DB_USER`/`DB_PASSWORD` in `.env`, and
  that SQL Server auth mode is set to "SQL Server and Windows Authentication"
  (not Windows-only).
- **`SSL Provider: The certificate chain was issued by an authority that is
  not trusted`** — this is why `.env.example` sets
  `DB_EXTRA_PARAMS=TrustServerCertificate=yes` for local dev. Remove it once
  you have a real certificate in production.
- **`Data source name not found`** — the ODBC driver name in `.env`
  (`DB_DRIVER`) doesn't match what `odbcinst -q -d` reports. Copy it exactly.

## Next phase

Phase 3 (Customer / KhataChit / ChitItem models with UUID PKs, all scoped to
`request.user`) starts once you confirm Phase 2 works against your actual
MSSQL instance.

---

# Phase 2: Custom Authentication & Security Base

## ⚠️ Read this before running migrate

`AUTH_USER_MODEL = 'khata_app.User'` is now set in `settings.py`. Django
bakes the user model into `auth`'s migration history the very first time
`migrate` ever runs against a database — it cannot be swapped afterwards
without dropping and recreating the DB.

- **If you already ran `migrate` back in Phase 1:** drop the database (or
  just the tables) and recreate it, then run `migrate` fresh now.
- **If Phase 1's `migrate` was never run against your real MSSQL yet:**
  nothing to do, just proceed normally below.

## What's new in this phase

- `khata_app/models.py` — custom `User` model extending `AbstractUser`, with
  a UUID primary key (`id`) instead of Django's default integer ID, plus
  `shop_name`, `phone_number`, `shop_address`
- `khata_app/forms.py` — `ShopkeeperRegistrationForm`, built on Django's
  `UserCreationForm` (inherits password-confirmation matching, the
  validators in `AUTH_PASSWORD_VALIDATORS`, and proper password hashing)
- `khata_app/views.py` — `register` (auto-logs-in on success) and a
  `dashboard` placeholder view guarded by `@login_required`
- `khata_app/urls.py` — `/register/`, `/login/`, `/logout/`, `/dashboard/`
  (login/logout use Django's own battle-tested `LoginView`/`LogoutView`
  rather than hand-rolled ones)
- `khata_app/admin.py` — custom user registered in Django admin
- `khata_app/templates/khata_app/` — `base.html`, `register.html`,
  `login.html`, `dashboard.html` (plain Bootstrap CDN, functional not
  pretty — real styling is Phase 7)
- `khata_app/migrations/0001_initial.py` — generated and included, so you
  don't need to run `makemigrations` yourself for this phase

## Verification steps for Phase 2

```bash
python manage.py migrate
python manage.py runserver
```

Then in the browser:

1. Go to `http://127.0.0.1:8000/register/`, fill in the form, submit —
   you should land straight on `/dashboard/` and see your shop name.
2. Go to `/logout/`, then try `/dashboard/` directly — you should get
   bounced to `/login/?next=/dashboard/`. That confirms the page is
   actually protected, not just hidden from the nav.
3. Log back in with the same credentials — you should land on
   `/dashboard/` again.
4. Open `/admin/`, log in with `createsuperuser` credentials, and confirm
   the shopkeeper appears under **Khata_App › Users** with `shop_name`
   visible.

I ran this exact flow (register → dashboard → logout → blocked → login)
against a local SQLite database using Django's test client before shipping
this, so the logic itself is confirmed — the only thing left to verify on
your end is the live MSSQL connection.

## Next phase

Phase 3 (Customer / KhataChit / ChitItem models, all scoped to
`request.user`) starts once you confirm Phase 2 works against your actual
MSSQL instance.

## What's new in this phase

- `khata_app/models.py` — `Customer`, `KhataChit`, `ChitItem` models, all
  with UUID primary keys and a `shopkeeper` FK (or FK-through-chit for
  `ChitItem`) so every row is traceable back to exactly one shopkeeper
- `khata_app/admin.py` — all three registered in Django admin. Non-superuser
  staff accounts only ever see their own shop's rows here too — the same
  "Query Scoping" rule from the security section applies inside the admin,
  not just in regular views
- `khata_app/migrations/0002_customer_khatachit_chititem.py` — generated
  and included

## Verification steps for Phase 3

```bash
python manage.py migrate
python manage.py createsuperuser   # if you don't already have one
python manage.py runserver
```

Then in `/admin/`: add a Customer, upload a KhataChit under it (any image
file works as a placeholder for now — the OCR pipeline in Phase 4 is what
actually reads it), and add a ChitItem under that chit. Confirm everything
shows up correctly linked.

I also ran an ORM-level test before shipping this: created two separate
shopkeepers with their own customers/chits/items, and confirmed a query
scoped to shopkeeper A never returns shopkeeper B's rows — tenant isolation
holds at the query level, which is the foundation every view in later
phases relies on.

---

# Phase 4: The AI & OCR Pipeline

## A note on the OCR engine

The roadmap listed EasyOCR *or* Tesseract. I went with **Tesseract**
(via `pytesseract` + OpenCV) rather than EasyOCR — both are legitimate
choices, but Tesseract's language packs install as small, ordinary OS
packages, so I could actually install and test the real Urdu+English
pipeline rather than just writing untested code against a multi-GB
deep-learning model I couldn't run here. If you'd rather use EasyOCR later,
`services.py` is written so only `extract_text()` would need to change —
`preprocess_image()` and `parse_chit_text()` don't care which OCR engine
produced the text.

## Fedora setup (run this on your dev machine)

```bash
sudo dnf install -y tesseract tesseract-langpack-urd tesseract-langpack-eng
tesseract --list-langs
# should list: eng, urd
```

## What's new in this phase

- `khata_app/services.py` — the pipeline, kept separate from `views.py`:
  - `preprocess_image()` — grayscale → denoise → adaptive threshold (handles
    the uneven lighting a handheld phone photo typically has)
  - `extract_text()` — Tesseract OCR with `lang="eng+urd"`
  - `parse_chit_text()` — a line-based heuristic that pulls out
    `(item_name, price)` pairs; whatever it can't confidently parse is
    returned separately as `unparsed_lines`, never silently guessed
  - `process_chit_image()` — the single entry point Phase 5's upload view
    will call
- `khata_app/management/commands/test_ocr.py` — a management command so you
  can test the pipeline against your own photos from the terminal
- `sample_data/test_chit_sample.png` — a synthetic printed (not handwritten)
  test chit with mixed English/Urdu lines, for a quick sanity check

## Verification steps for Phase 4

```bash
python manage.py test_ocr sample_data/test_chit_sample.png

# once you have a real photo of a handwritten chit:
python manage.py test_ocr /path/to/your/photo.jpg
```

### What I actually got testing this myself

Against the synthetic sample image, the pipeline extracted 3 of 4 lines
correctly:

```
Sugar 2kg  -> 240   ✓
Tea 1      -> 90    ✓ (though "Tea" itself was misread as "Teal")
Rice 5kg   -> 650   ✓
دودھ 1 لیٹر 180  -> NOT parsed — Tesseract garbled the Urdu Nastaliq
                     script entirely (this is a known hard problem —
                     Nastaliq's connected, diagonal letterforms are much
                     harder for OCR than upright Naskh-style Arabic script)
```

**This is the honest result, not a cherry-picked one** — and it's exactly
why Phase 5 exists: the roadmap already calls for a human-in-the-loop
review step rather than trusting OCR output directly, and this confirms
that's a necessary design choice, not a formality. Expect real handwritten
chits (as opposed to this printed test image) to need even more correction.
If Urdu accuracy turns out too low to be useful in practice once you're
testing on real chits, swapping in EasyOCR (which has a dedicated Urdu
handwriting model) is the natural next thing to try — `services.py` is
structured so that's a contained change.

## Next phase

Phase 5 (upload view that runs a chit through this pipeline, then shows the
shopkeeper an editable review form before saving anything to `ChitItem`)
starts once you confirm Phases 3 and 4 work on your end.

---

# Phase 5: Core Application Logic (Upload & Extract)

## What's in this phase

- `khata_app/forms.py` — `ChitUploadForm` (image + customer, scoped to the
  logged-in shopkeeper's own customers) and `ChitItemForm`/`ChitItemFormSet`
  for the review step
- `khata_app/views.py` — `chit_upload` (saves the image, runs the Phase 4
  OCR pipeline, shows an editable review form) and `chit_review` (only
  point where `ChitItem` rows actually get saved — never trusts OCR output
  directly)
- `khata_app/templates/khata_app/upload_chit.html` and `review_chit.html`
- `KhataChit.ocr_raw_text` / `ocr_processed_at` — new fields caching what
  the pipeline actually saw, for debugging misreads later
- Migration `0003_khatachit_ocr_processed_at_khatachit_ocr_raw_text.py`

## Two real bugs I found and fixed while testing this

I ran this end-to-end (upload → review → save) before shipping it, the same
way I tested Phases 3 and 4, and it caught two genuine bugs in the review
formset — not hypothetical edge cases, things that would have broken for
you on real use:

1. **OCR results beyond the 3rd item were silently dropped.** The review
   formset's blank-row count was fixed at `extra=3`. A chit with only 1–3
   items looked fine in testing, but a chit with, say, 6 items would only
   ever show the first 3 — the rest vanished before the shopkeeper even
   saw them, with no error or warning. Fixed by sizing the formset to the
   actual number of OCR-detected items (plus a few spare rows), computed
   per-upload in `chit_upload`.

2. **Submitting the review failed whenever any spare blank row was left
   untouched** — which is the normal case, since shopkeepers only fill in
   what's actually on the chit. This was caused by `ChitItem.quantity`
   having `default=1` at the model level: Django's form machinery carried
   that default into the form as `initial=1`, so an untouched blank row
   (submitted as empty) looked to Django like "this row changed from 1 to
   empty" instead of "this row was never touched" — which triggered full
   validation on a row nobody filled in, failing with a spurious "This
   field is required" and blocking the *entire* save, not just that row.
   Fixed in `ChitItemForm` by not inheriting that default into the form
   field, with the same default re-applied — correctly, only to rows the
   shopkeeper actually used — in a `clean_quantity()` step.

Both are exactly the kind of bug that hides in a quick manual test (upload
a chit with 2–3 items, fill in every row) and only shows up under real
usage. I mention them because you should know the review flow was actually
exercised end-to-end, not just written and assumed to work.

## Verification steps for Phase 5

```bash
python manage.py migrate
python manage.py runserver
```

Then in the browser:

1. Log in, click "Upload a chit," upload a photo (your own real chit
   photo, or `sample_data/test_chit_sample.png` for a quick check).
2. Confirm you land on a review page pre-filled with whatever OCR found —
   for a busier chit, count the rows to make sure nothing's missing.
3. Correct any wrong item names/prices, leave a couple of spare rows
   blank, optionally use a blank row to add something OCR missed
   entirely, then click "Save to Khata."
4. Confirm you land back on the dashboard with a "Saved N item(s)"
   message, and the chit's item count updates.
5. In `/admin/`, confirm the `ChitItem` rows are there under the right
   chit, and that `KhataChit.ocr_raw_text` shows what OCR actually
   extracted (handy for spot-checking accuracy over time).

I ran this full flow via Django's test client before sending this,
including a deliberate cross-tenant attempt (one shopkeeper trying to
submit a review against another shop's chit ID) — confirmed 404, no data
leaked or written.

## Next phase

Phase 6 (real analytics dashboard — totals, credit pending, date filters)
starts once you confirm Phase 5 works on your end.

---

# Phase 6: Dashboard & Analytics

## A note on "estimated profit"

The original roadmap's `ChitItem` model had no field for what a shopkeeper
actually *paid* for an item — without that, "profit" would just be total
sales relabeled, which would be actively misleading about real margins. I
added an optional `cost_price` field (Phase 6, migration `0004`) rather than
fabricate a number. It's genuinely optional: leave it blank and the
dashboard tells you plainly there's no cost data yet, instead of quietly
showing revenue as if it were profit.

## What's new in this phase

- `khata_app/analytics.py` — `compute_dashboard_totals()`, kept separate
  from `views.py` so the math is unit-testable on its own. Deliberately
  done in Python rather than a database-level aggregate: `price`/
  `cost_price` are `DecimalField` but `quantity` is `FloatField`, and
  multiplying Decimal × Float inside a Django ORM `F()` expression behaves
  inconsistently across database backends (SQLite is forgiving, MSSQL is
  stricter). A single shop's data volume is small enough that plain Python
  summation is both simpler and more portable.
- `dashboard` view — now takes `?period=today|week|month|all`, scoped to
  `request.user` first and the date range applied on top, never instead of
  it (so switching ranges can never leak another shopkeeper's data)
- `khata_app/templates/khata_app/dashboard.html` — period filter buttons +
  four totals cards (sales, credit pending, received, estimated profit)
- `khata_app/forms.py` — `ChitItemForm` now includes the optional
  `cost_price` field so shopkeepers can enter it during Phase 5's review
  step (the only place it realistically gets entered)

## An important note on "Quantity" — read this before you rely on the totals

The dashboard totals are `price × quantity`. Phase 4's OCR pipeline reads a
line like "Sugar 2kg — 240" as `item_name="Sugar 2kg"`, `price=240`,
`quantity=1` (the "2kg" stays as text in the name, not a separate number) —
so by default the math works out correctly (240 × 1 = 240). But if you
manually change Quantity to 2 because the name says "2kg", you'll silently
double that line's contribution to your totals. I added an inline warning
on the review page about this, but it's worth knowing about directly rather
than discovering it in your sales numbers.

## Verification steps for Phase 6

```bash
python manage.py migrate
python manage.py runserver
```

1. Upload a couple of chits, reviewing/saving items for each — enter a
   cost on at least one item to see the profit card populate.
2. On the dashboard, click through Today / This week / This month / All
   time and confirm the numbers change sensibly as you'd expect from what
   you just entered.
3. Confirm "Credit pending" only reflects items you checked "Credit?" on,
   and "Received" = "Total sales" − "Credit pending".

I tested this by backdating chits to known dates (bypassing
`auto_now_add`) and independently computing the expected total for each
date range in a separate script, then confirming the dashboard's numbers
matched exactly — for today, this week, this month, and all-time. I also
unit-tested `compute_dashboard_totals()` directly against hand-calculated
numbers (sales, credit, profit, and the "partial profit" flag) before
wiring it into the view.

## Next phase

Phase 7 (UI polish, mobile responsiveness, final security audit) starts
once you confirm Phase 6 works on your end.

---

# Phase 7: UI Refinement & Final Polish

## What's new in this phase

- **Responsive navbar** — was `navbar-expand` with no breakpoint, meaning
  it could never collapse on a small screen. Now `navbar-expand-md` with a
  proper hamburger toggler, and Dashboard/Upload links moved into it.
- **Bootstrap's JS bundle was never actually included before this** — only
  the CSS was linked, so nothing interactive (the navbar toggler, dismiss
  buttons) could have worked even where the markup already looked right.
  Added `bootstrap.bundle.min.js`.
- **Real toast notifications** — success/error messages were static
  full-width alerts pinned to the top of the page. Now they're actual
  Bootstrap toasts, fixed bottom-right, auto-dismissing, individually
  closable — and I added `MESSAGE_TAGS` in `settings.py` mapping Django's
  `"error"` tag to Bootstrap's `"danger"`, since `text-bg-error` isn't a
  real Bootstrap class and errors would otherwise render unstyled.
- **Responsive tables** — both the dashboard's recent-chits table and the
  review page's item table are now wrapped in `.table-responsive`, so they
  scroll horizontally on a narrow phone screen instead of squishing
  unreadably.
- **Responsive image** — the uploaded chit preview on the review page now
  has `img-fluid` alongside `img-thumbnail`, so it scales down on small
  screens instead of overflowing.

## Final security audit

I went through every view and every query against the same rules from the
top of this document (tenant isolation, UUID PKs, query scoping,
`@login_required`, CSRF) rather than just asserting they're fine:

| Check | Result |
|---|---|
| Every view that touches user data has `@login_required` | ✅ `dashboard`, `chit_upload`, `chit_review` all decorated; `register` is correctly the only undecorated one (it has to be public) |
| Every `KhataChit`/`ChitItem` query is scoped to `request.user` | ✅ Checked every `.objects.` / `.filter(` / `get_object_or_404` call in `views.py` by hand |
| No `@csrf_exempt` anywhere | ✅ grepped the whole app, none found |
| No raw SQL (`.raw()`, `cursor()`) | ✅ grepped the whole app, none found |
| `SECRET_KEY` / `DEBUG` come from `.env`, not hardcoded | ✅ (see `.env.example`) |
| Admin panel respects tenant isolation, not just regular views | ✅ (`ScopedToShopkeeperAdmin`, Phase 3) |

I also specifically tried a subtler attack I wanted to rule out rather than
assume was fine: since `chit_review`'s formset is bound with
`queryset=ChitItem.objects.none()`, I tested whether submitting a review
with a forged hidden `id` field pointing at *another shop's* existing
`ChitItem` could hijack/overwrite that row. It can't — Django only resolves
that `id` field against the given queryset (empty here), so the forged ID
is silently ignored and a normal new row gets created under the attacker's
*own* chit instead. No cross-tenant data was reachable. I'm including this
because "I checked X" is worth more when X was an actual test run against
the code, not just a description of how it's supposed to work.

### One thing worth doing yourself before going live

`DEBUG=True` is still the default in `.env.example` for local development
convenience. **Before deploying anywhere real, set `DEBUG=False` in your
production `.env`** — with `DEBUG=True`, an unhandled error shows a full
stack trace (including your file paths and settings) to anyone who
triggers it.

## Verification steps for Phase 7

```bash
python manage.py runserver
```

1. Open the site in your browser at a narrow width (or actual phone) —
   confirm the navbar collapses into a hamburger menu and the dashboard
   cards/table don't overflow horizontally.
2. Trigger a message (e.g. save a chit review) and confirm it appears as a
   dismissible toast in the bottom-right corner rather than a static bar
   at the top.
3. Trigger an error message somewhere (e.g. submit an invalid form) if you
   want to see the red/"danger" toast styling specifically.

## All seven phases are now complete

That's the full roadmap from the original spec: environment setup, auth,
data models, the OCR pipeline, upload-and-review, analytics, and polish.
The natural next steps beyond the original roadmap, if you want them
later, would be things like: a customer-facing view of their own credit
history, exporting reports (CSV/PDF), or swapping Tesseract for EasyOCR if
Urdu accuracy on real handwriting turns out to need it. But none of that
was asked for — this is a complete, working system against the original
7-phase plan.
