# AGENT.md — Developer & AI Agent Guidelines

This document provides system architecture, development workflows, rules, and commands for AI agents and developers working on the **Khata Digitizer & Micro-Credit Scorer** codebase.

---

## 1. Project Overview & Architecture

* **Application Name**: Khata Digitizer & Micro-Credit Scorer
* **Framework**: Django 6.1.1 (Python 3.14)
* **Database**: Microsoft SQL Server via `mssql-django` + `pyodbc` (ODBC Driver 18)
* **Time Zone**: `Asia/Karachi`
* **Root Workspace**: `/home/moosaabbasi/Desktop/khata_digitizer_phase6_7/`
* **Django Directory**: `/home/moosaabbasi/Desktop/khata_digitizer_phase6_7/khata_digitizer/`

### Directory Layout
```text
khata_digitizer_phase6_7/
├── AGENT.md                          # Agent instructions & development guidelines
└── khata_digitizer/
    ├── manage.py                     # Django management CLI
    ├── requirements.txt              # Project dependencies
    ├── README.md                     # Roadmap documentation (Phases 1-7)
    ├── .env                          # Local credentials (DB_NAME, DB_USER, DB_PASSWORD, etc.)
    ├── khata_project/                # Project configuration (settings, root urls, wsgi/asgi)
    └── khata_app/                    # Core application
        ├── models.py                 # Custom User, Customer, KhataChit, ChitItem
        ├── views.py                  # Auth, Dashboard, Chit Upload/Review, Details, Credit Khata
        ├── urls.py                   # App routing endpoints
        ├── forms.py                  # User registration, Chit upload, ChitItem review formsets
        ├── analytics.py              # Financial calculation logic (totals, credit, profit)
        ├── services.py               # AI & OCR processing pipeline
        ├── admin.py                  # Tenant-scoped Django admin interfaces
        ├── tests.py                  # Unit and integration test suite
        ├── migrations/               # Database schema migration history
        └── templates/khata_app/      # Responsive Bootstrap 5 templates
```

---

## 2. Environment & Execution Guidelines

### Active Python Virtual Environment
* **Virtualenv Path**: `/home/moosaabbasi/.local/share/virtualenvs/khata_digitizer-9D37e55J/`
* **Activation Command**:
  ```bash
  source /home/moosaabbasi/.local/share/virtualenvs/khata_digitizer-9D37e55J/bin/activate
  ```

### Essential Commands
> **Always run commands from inside the `khata_digitizer/` directory.**

* **Run Dev Server**:
  ```bash
  python manage.py runserver
  ```
* **Apply Migrations to Database**:
  ```bash
  python manage.py migrate
  ```
  *(Note: `makemigrations` creates migration files on disk, but `migrate` is required to actually update SQL Server tables and columns).*
* **Create New Migrations**:
  ```bash
  python manage.py makemigrations
  ```
* **Run Test Suite**:
  ```bash
  python manage.py test
  ```
* **Test OCR Pipeline CLI**:
  ```bash
  python manage.py test_ocr sample_data/test_chit_sample.png
  ```

---

## 3. Data Models & Business Logic

### Core Models (`khata_app/models.py`)
1. **`User`** (`AbstractUser`):
   * Primary key: UUID (`uuid.uuid4`).
   * Extra fields: `shop_name`, `phone_number`, `shop_address`.
   * Configured as `AUTH_USER_MODEL = 'khata_app.User'`.
2. **`Customer`**:
   * Scoped to `shopkeeper` (Foreign key to `User`).
   * Tracks customer name and contact details.
3. **`KhataChit`**:
   * Scoped to `shopkeeper`.
   * Optionally linked to `Customer`.
   * Stores the receipt photo (`image`), `ocr_raw_text`, and processing timestamp.
4. **`ChitItem`**:
   * Linked to `KhataChit` via Foreign Key (`related_name="items"`).
   * Fields: `item_name`, `quantity`, `price`, `cost_price` (optional), `is_credit`, `is_paid`, `paid_at`.

### Financial Calculation Rules (`khata_app/analytics.py`)
* **Line Total**: `price * quantity`.
* **Total Sales**: Sum of all line totals.
* **Credit Pending (To Collect)**: Sum of items where `is_credit=True` AND `is_paid=False`.
* **Received Sales**: `total_sales - total_credit_pending` (All cash sales + settled credit items).
* **Estimated Profit**: Sum of `(price - cost_price) * quantity` for items where `cost_price` is provided.

---

## 4. Critical Security & Architecture Invariants

1. **Tenant Isolation (Multi-Tenancy)**:
   * Every database query touching `Customer`, `KhataChit`, or `ChitItem` **MUST** be scoped to `request.user` (`shopkeeper=request.user` or `chit__shopkeeper=request.user`).
   * Never look up a chit or customer by ID without validating shopkeeper ownership (`get_object_or_404(..., shopkeeper=request.user)`).
   * The Django admin mirrors this via `ScopedToShopkeeperAdmin`.
2. **Authentication Protection**:
   * All functional application views must be protected with `@login_required` (except public views: `register` and `login`).
   * **Logout Handling**: Django 5.0+ rejects GET requests to `LogoutView` with HTTP 405. `views.user_logout` handles both GET and POST requests gracefully. Navigation forms use POST with `{% csrf_token %}`.
3. **Human-in-the-Loop OCR Verification**:
   * OCR output is **never** saved directly to `ChitItem`.
   * Photo upload saves the `KhataChit` image and parses raw text into a dynamic `ChitItemFormSet` on `review_chit.html`. The shopkeeper must review, edit, and click "Save to Khata" before items are committed to the database.

---

## 5. AI / OCR Roadmap

* **Current Implementation**: Tesseract (`eng+urd`) with OpenCV preprocessing in `khata_app/services.py`.
* **Planned Enhancement**: Training a custom AI model using a dedicated Urdu/English handwritten receipt dataset provided by the user.
* **Architecture Rule**: Keep `process_chit_image()` in `services.py` decoupled from views and forms so switching or fine-tuning the OCR model requires no modifications to the rest of the web application.

---

## 6. Recent Modifications & Bug Fixes (Phase 6 / 7 Stabilization)

### Issue: Unknown field `is_paid` on `ChitItem` & Migration Sync
* **Symptom**: Running `python manage.py check` or `runserver` failed with `django.core.exceptions.FieldError: Unknown field(s) (is_paid) specified for ChitItem`.
* **Root Causes**:
  1. `ChitItem` model in `khata_app/models.py` was missing the `is_paid` and `paid_at` fields as well as the `@property line_total`.
  2. Migration `0005_chititem_is_paid_chititem_paid_at.py` was unapplied in the database.
  3. The root URL (`""`) was not routed in `khata_app/urls.py`, resulting in 404 when accessing `http://127.0.0.1:8000/`.
* **Changes Applied**:
  * **`khata_app/models.py`**:
    * Imported `Decimal` from Python's `decimal` module.
    * Restored `is_paid = models.BooleanField(default=False, help_text="Only meaningful when is_credit is True. Marks a credit entry as settled.")` on `ChitItem`.
    * Restored `paid_at = models.DateTimeField(null=True, blank=True, help_text="When the customer settled this credit item.")` on `ChitItem`.
    * Added `line_total` property on `ChitItem` returning `Decimal(str(self.price)) * Decimal(str(self.quantity))` for monetary calculations across views and templates.
  * **Database Migration**:
    * Ran `python manage.py migrate` to apply migration `0005_chititem_is_paid_chititem_paid_at`.
  * **`khata_app/urls.py`**:
    * Added root redirect route: `path("", RedirectView.as_view(pattern_name="dashboard", permanent=False), name="home")` to automatically direct users landing on `/` to `/dashboard/`.
