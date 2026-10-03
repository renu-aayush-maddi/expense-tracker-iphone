# Personal Expense Tracker

A personal expense tracker with a React dashboard, a FastAPI backend, PostgreSQL storage, and **automatic PhonePe imports from an iPhone Shortcut**.

```
PhonePe → Share Receipt → iPhone Shortcut (OCR only) → FastAPI → Parser → Duplicate check → PostgreSQL → React dashboard
```

---

## Contents

1. [Project overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Technologies](#3-technologies)
4. [Local setup](#4-local-setup)
5. [PostgreSQL setup](#5-postgresql-setup-local)
6. [Environment variables](#6-environment-variables)
7. [Backend setup](#7-backend-setup)
8. [Frontend setup](#8-frontend-setup)
9. [Database migrations](#9-database-migrations)
10. [Running tests](#10-running-tests)
11. [Supabase setup](#11-supabase-setup)
12. [Render deployment](#12-render-deployment)
13. [iPhone Shortcut setup](#13-iphone-shortcut-setup)
14. [PhonePe import workflow](#14-phonepe-import-workflow)
15. [End-to-end test](#15-end-to-end-test)
16. [Troubleshooting](#16-troubleshooting)
17. [API reference](#17-api-reference)
18. [Extending: new import sources](#18-extending-new-import-sources)

---

## 1. Project overview

What you can do:

- Add, edit and delete expenses by hand (amount, merchant, category, date, time, payment method, bank, notes)
- Browse every transaction with search, filters (date, month, year, category, bank, payment method, source, amount range), sorting and pagination
- See a dashboard with this month's total, today's spending, transaction count, average, largest expense, spending by category, bank and payment method, daily and monthly charts, yearly totals and recent transactions
- **Import PhonePe payments automatically**: share the receipt to the "Phonepay Automation" Shortcut and the expense appears in the app
- Review imports that couldn't be read confidently. Nothing uncertain is saved silently.
- Duplicate protection: sharing the same receipt twice never creates two transactions

**The key design decision:** the iPhone Shortcut only does OCR and one HTTP request. **All the intelligence lives in the backend**: parsing, amount and merchant extraction, IDs, date and time, account, category, validation, duplicate detection and storage. If PhonePe changes its receipt layout, you only update `backend/app/services/phonepe_parser.py`.

---

## 2. Architecture

```
┌──────────────────────┐        ┌───────────────────────────────────────────────┐        ┌──────────────┐
│  iPhone Shortcut     │  POST  │  FastAPI backend (Render Web Service)         │  SQL   │  PostgreSQL  │
│  1. receive image    │───────►│                                               │───────►│  (Supabase)  │
│  2. extract text     │  JSON  │  api/imports.py  → services/transaction_      │        └──────────────┘
│  3. send raw OCR     │        │                     importer.py               │               ▲
└──────────────────────┘        │      ├─ phonepe_parser.py   (parse OCR)       │               │
                                │      ├─ categorizer.py      (suggest category)│               │
┌──────────────────────┐  REST  │      ├─ duplicate_detector.py (ID/UTR/fallback│               │
│  React app           │◄──────►│      └─ transaction_service.py (save)         │───────────────┘
│  (Render Static Site)│  JWT   │  api/transactions.py, stats.py, auth.py ...   │
└──────────────────────┘        └───────────────────────────────────────────────┘
```

### Folder structure

```
expense-tracker/
├── backend/
│   ├── app/
│   │   ├── api/            # HTTP routes (thin): auth, transactions, imports, stats, settings, meta
│   │   ├── core/           # config, security (bcrypt/JWT), rate limiter, middleware, constants
│   │   ├── db/             # SQLAlchemy Base + engine/session
│   │   ├── models/         # User, Transaction, PendingImport, ApiToken, BankAccount
│   │   ├── schemas/        # Pydantic request/response models (validation)
│   │   ├── services/       # business logic: parsers, importer, categorizer, duplicates, stats
│   │   └── main.py         # FastAPI app, CORS, error handlers, security headers
│   ├── alembic/            # database migrations
│   ├── tests/              # pytest suite (148 tests)
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/     # Layout, TransactionForm, TransactionTable, filters, charts...
│   │   ├── pages/          # Login, Register, Dashboard, Transactions, Detail, Add, Import, Review, Settings
│   │   ├── services/       # API client (fetch + JWT) and one file per backend area
│   │   ├── hooks/          # useAuth, useApi, useMeta
│   │   ├── utils/          # money/date formatting
│   │   ├── App.jsx         # routes
│   │   └── main.jsx
│   ├── package.json
│   └── .env.example
├── render.yaml             # Render Blueprint (both services)
└── README.md
```

### Database tables

| Table | Purpose |
|---|---|
| `users` | Accounts. Passwords are bcrypt hashes, never plaintext. |
| `transactions` | Every expense. `amount` is `NUMERIC(12,2)`, never float. Unique `(user_id, phonepe_transaction_id)` and `(user_id, utr)` stop duplicates at the database level. |
| `pending_imports` | Imports that need review: the parsed guess, the list of issues and the raw OCR. Unique per receipt text, so re-sharing doesn't create two reviews. |
| `api_tokens` | Personal import tokens for the Shortcut. Only a SHA-256 hash is stored. |
| `bank_accounts` | Maps account last-4 digits to a bank name (e.g. 6929 → Kotak). |

### Why the Shortcut uses an "import token" instead of a JWT

JWTs expire after 7 days, and a Shortcut can't log in. So in **Settings** you create a long-lived **import token** (`etk_…`) and paste it into the Shortcut. It's stored hashed, can be deleted at any time, and **only works on the import endpoint**. It can't read or change your other data.

---

## 3. Technologies

| Layer | Tech |
|---|---|
| Frontend | React 19, Vite, React Router, Recharts, plain CSS (no Tailwind) |
| Backend | Python, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg 3 |
| Auth | bcrypt password hashing, JWT (PyJWT), hashed personal import tokens |
| AI fallback (optional) | OpenAI Responses API with structured outputs (`openai` SDK) |
| Database | PostgreSQL (Supabase in production; any Postgres works, since only `DATABASE_URL` changes) |
| Hosting | Render Static Site (frontend), Render Web Service (backend) |
| Tests | pytest + FastAPI TestClient (SQLite by default, or PostgreSQL) |

---

## 4. Local setup

**Prerequisites**

- Python **3.12+** (tested on 3.13 and 3.14)
- Node.js **20+** (tested on 24)
- PostgreSQL **14+** running locally (macOS: `brew install postgresql@16 && brew services start postgresql@16`)

**Quick start** (two terminals):

```bash
# Terminal 1: backend
cd backend
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # then edit DATABASE_URL and JWT_SECRET (see below)
alembic upgrade head                 # create the tables
uvicorn app.main:app --reload        # http://localhost:8000  (API docs: /docs)

# Terminal 2: frontend
cd frontend
npm install
cp .env.example .env                 # VITE_API_URL=http://localhost:8000
npm run dev                          # http://localhost:5173
```

Open http://localhost:5173, create an account, and you land on the dashboard.

---

## 5. PostgreSQL setup (local)

```bash
createdb expense_tracker
createdb expense_tracker_test        # optional: for running tests against Postgres
```

Then in `backend/.env`:

```
DATABASE_URL=postgresql://YOUR_MAC_USERNAME@localhost:5432/expense_tracker
```

(With a password: `postgresql://user:password@localhost:5432/expense_tracker`.)

You never create tables by hand. `alembic upgrade head` creates them.

---

## 6. Environment variables

### Backend (`backend/.env` locally, Render "Environment" tab in production)

| Variable | Required | Example | Notes |
|---|---|---|---|
| `DATABASE_URL` | ✅ | `postgresql://…` | `postgres://` and `postgresql://` are both accepted; the app switches to the psycopg driver itself. |
| `JWT_SECRET` | ✅ | 64+ random chars | Generate: `python3 -c "import secrets; print(secrets.token_urlsafe(64))"`. Must be at least 32 chars. |
| `JWT_ALGORITHM` | | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | | `10080` | 7 days |
| `CORS_ORIGINS` | ✅ in prod | `https://expense-tracker-web.onrender.com` | Comma separated, no trailing slash |
| `ENVIRONMENT` | | `production` | Enables HSTS header |
| `ALLOW_REGISTRATION` | | `true` | **Set to `false` after you've created your account** |
| `APP_TIMEZONE` | | `Asia/Kolkata` | Used for "today" and "this month" |
| `ENABLE_DOCS` | | `true` | Swagger UI at `/docs` |
| `MAX_REQUEST_BYTES` | | `65536` | Request size limit |
| `IMPORT_RATE_LIMIT_PER_MINUTE` | | `30` | Per user |
| `LOGIN_RATE_LIMIT_PER_MINUTE` | | `10` | Per IP |
| `OPENAI_API_KEY` | optional | `sk-…` | Turns on the AI fallback for hard-to-read receipts. Leave empty to disable. |
| `OPENAI_MODEL` | | `gpt-5.4-mini` | Any OpenAI model that supports structured outputs |
| `LLM_FALLBACK_ENABLED` | | `true` | Switch the fallback off without removing the key |
| `LLM_TIMEOUT_SECONDS` | | `20` | After this, the import goes to review instead |

### Frontend (`frontend/.env` locally, Render static site env in production)

| Variable | Example |
|---|---|
| `VITE_API_URL` | `http://localhost:8000` locally, `https://expense-tracker-api.onrender.com` in production |

> `VITE_*` values are baked in **at build time**. After changing `VITE_API_URL` on Render, redeploy the static site.

Secrets are never committed: `.env` is in `.gitignore`; only `.env.example` files are tracked.

---

## 7. Backend setup

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

- Health check: http://localhost:8000/api/health → `{"status":"ok"}`
- Interactive API docs: http://localhost:8000/docs. Click **Authorize** and paste a token from `/api/auth/login`.

Quick test with curl:

```bash
# register
curl -X POST localhost:8000/api/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"supersecret123"}'

# add an expense (use the access_token from the response above)
curl -X POST localhost:8000/api/transactions -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"amount":"500","merchant_name":"Zomato","category":"Food","transaction_date":"2026-10-03","payment_method":"UPI","bank":"Kotak","notes":"Dinner"}'
```

## 8. Frontend setup

```bash
cd frontend
npm install
npm run dev       # development server with hot reload
npm run build     # production build into dist/
npm run preview   # serve the production build locally
```

Pages: `/login`, `/register`, `/dashboard`, `/transactions`, `/transactions/:id`, `/add-expense`, `/import`, `/imports/:id` (review), `/settings`.

---

## 9. Database migrations

Migrations live in `backend/alembic/versions/`. Two are included:

1. `initial schema`: every table, constraint and index
2. `enable row level security`: blocks Supabase's auto-generated REST API from reading your tables. The backend is unaffected because it connects as the table owner.

All commands run from `backend/` with the venv active:

| Task | Command |
|---|---|
| Apply all migrations (upgrade) | `alembic upgrade head` |
| Undo the last migration (downgrade) | `alembic downgrade -1` |
| Undo everything | `alembic downgrade base` |
| Show current version | `alembic current` |
| Show history | `alembic history` |
| Create a new migration after changing a model | `alembic revision --autogenerate -m "add xyz column"` |

If you start from an empty `versions/` folder, generate the initial migration with:

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

On Render, `alembic upgrade head` runs automatically on every start (see the start command).

---

## 10. Running tests

```bash
cd backend
source .venv/bin/activate
pytest                      # uses in-memory SQLite: no database needed
```

Against real PostgreSQL (recommended before deploying):

```bash
TEST_DATABASE_URL=postgresql://YOUR_USER@localhost:5432/expense_tracker_test pytest
```

What's covered (148 tests): registration, login, `/me`, password hashing, rate limiting; transaction create/read/update/delete, validation, filters, search, pagination, user isolation; PhonePe parsing (amount in every format: ₹, ¥, Rs, INR, spaces, lakhs), contextual amount extraction, transaction ID (spaces, OCR `O`→`0`, `7`→`T`), UTR, account last 4, dates and times; duplicate detection (same receipt, same UTR, same ID, per-user); invalid OCR; real receipt layouts (amount on the account row, every misread ₹ symbol, UPI handle glued to the merchant); the AI fallback with a mocked model (verified amounts only, no dates as amounts, no identifiers sent, errors fall back to review); review-required flow, confirm, discard and "retry all"; import tokens; request size limits; dashboard maths.

---

## 11. Supabase setup

**Free?** Yes. The free plan includes a 500 MB database. Free projects **pause after 7 days without activity**; unpause from the dashboard if that happens.

1. Go to **https://supabase.com** → **Start your project** → sign in with GitHub.
2. **New project**
   - Name: `expense-tracker`
   - Database password: click **Generate a password** and **save it** in your password manager
   - Region: **Mumbai (ap-south-1)** if you're in India (closest to you; pick a nearby Render region too)
   - Plan: Free
3. Wait ~2 minutes for the project to be ready.
4. Click **Connect** (top of the project page) → **Connection String** tab → Type **URI** → choose **Session pooler**.
   > Use the **Session pooler**, not "Direct connection". The direct connection is IPv6-only and Render can't reach it.
5. Copy the string. It looks like:
   ```
   postgresql://postgres.abcdefghijklmnop:[YOUR-PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
   ```
6. Replace `[YOUR-PASSWORD]` with your database password and add `?sslmode=require` at the end:
   ```
   postgresql://postgres.abcdefghijklmnop:MyS3cretPass@aws-0-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require
   ```
   If the password contains special characters, URL-encode them: `@` → `%40`, `#` → `%23`, `/` → `%2F`, `:` → `%3A`, `%` → `%25`.
7. This full string is your **`DATABASE_URL`** for Render. Keep it secret.
8. Optional extra hardening: **Project Settings → Data API** → turn the Data API off (this app doesn't use it; the RLS migration already blocks it).

You don't create any tables in Supabase. Alembic creates them on the first Render deploy. Afterwards you can see them under **Table Editor**.

*(Optional) test the connection from your Mac before deploying:*

```bash
cd backend && source .venv/bin/activate
DATABASE_URL='postgresql://postgres.xxx:PASS@aws-0-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require' alembic upgrade head
```

---

## 12. Render deployment

**Free?** Yes. Static sites are free; one free web service is enough. Free web services **sleep after 15 minutes idle** and take ~30–60 s to wake (see [Troubleshooting](#16-troubleshooting)). HTTPS is automatic.

### Step 1: Push the code to GitHub

```bash
cd expense-tracker
git init
git add .
git commit -m "Expense tracker"
# create an EMPTY private repo on github.com (no README), then:
git remote add origin https://github.com/YOUR_USERNAME/expense-tracker.git
git branch -M main
git push -u origin main
```

Check that `backend/.env` and `frontend/.env` were **not** pushed (`.gitignore` excludes them).

### Step 2 (option A, easiest): Blueprint

1. **https://dashboard.render.com** → sign in with GitHub → **New +** → **Blueprint**.
2. Pick your `expense-tracker` repo. Render reads `render.yaml` and shows two services: `expense-tracker-api` and `expense-tracker-web`.
3. It asks for the values marked `sync: false`:
   - `DATABASE_URL`: your Supabase string from section 11
   - `CORS_ORIGINS`: `https://expense-tracker-web.onrender.com`
   - `VITE_API_URL`: `https://expense-tracker-api.onrender.com`

   (These are the usual URLs. If a name is taken, Render adds a suffix; fix them in step 3.)
4. Click **Apply**. `JWT_SECRET` is generated automatically.
5. When both are live, open each service and check its real URL at the top of its page. If either differs from what you entered:
   - API service → **Environment** → fix `CORS_ORIGINS` → **Save** (it redeploys)
   - Static site → **Environment** → fix `VITE_API_URL` → **Save**, then **Manual Deploy → Deploy latest commit** (Vite bakes this in at build time)

### Step 2 (option B): create the services by hand

**Backend: New + → Web Service** → connect the repo:

| Setting | Value |
|---|---|
| Name | `expense-tracker-api` |
| Region | Singapore (closest to Mumbai) |
| Root Directory | `backend` |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips "*"` |
| Health Check Path | `/api/health` (under Advanced) |
| Instance type | Free |

Environment variables for the backend:

| Key | Value |
|---|---|
| `PYTHON_VERSION` | `3.13.7` |
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | Supabase Session pooler URI with `?sslmode=require` |
| `JWT_SECRET` | output of `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `JWT_ALGORITHM` | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` |
| `CORS_ORIGINS` | `https://YOUR-FRONTEND.onrender.com` |
| `ALLOW_REGISTRATION` | `true` (change to `false` after registering) |
| `APP_TIMEZONE` | `Asia/Kolkata` |
| `OPENAI_API_KEY` | optional: your OpenAI key (enables the AI fallback, see section 14) |
| `OPENAI_MODEL` | `gpt-5.4-mini` |

**Frontend: New + → Static Site** → same repo:

| Setting | Value |
|---|---|
| Name | `expense-tracker-web` |
| Root Directory | `frontend` |
| Build Command | `npm ci && npm run build` |
| Publish Directory | `dist` |
| Env var `VITE_API_URL` | `https://YOUR-BACKEND.onrender.com` |

Then **Redirects/Rewrites** tab → add a rule: Source `/*`, Destination `/index.html`, Action **Rewrite**. Without it, refreshing on `/transactions` shows "Not Found".

### Step 3: Verify

1. `https://YOUR-BACKEND.onrender.com/api/health` → `{"status":"ok"}`
2. Open `https://YOUR-FRONTEND.onrender.com` → **Create account**
3. Backend → Environment → `ALLOW_REGISTRATION` = `false` → Save. Nobody else can sign up now.
4. Supabase → Table Editor: you'll see `users`, `transactions`, etc.

---

## 13. iPhone Shortcut setup

Do this **after** deploying.

### 13.1 Get your two values from the web app

1. Open your deployed app → **Settings** → **iPhone Shortcut**.
2. Copy the **Import URL**: `https://YOUR-BACKEND.onrender.com/api/transactions/import/phonepe`
3. Click **Create import token**, then **copy the token now** (`etk_…`). It is shown only once. If you lose it, delete it and create a new one.

### 13.2 Rebuild "Phonepay Automation"

Open **Shortcuts** → long-press **Phonepay Automation** → **Edit**.

**Remove all existing actions** (any regex, Match Text, Get Group, or amount extraction). Tap the ⊖ / swipe left on each.

Then build it like this, top to bottom:

| # | Action (search for it in the action list) | Configure it |
|---|---|---|
| 0 | *(top of shortcut)* **Receive … from Share Sheet** | Tap the input type → select **Images** only. "If there's no input" → **Stop and Respond**. *(If missing: tap the ⓘ / name menu → Details → turn on **Show in Share Sheet**.)* |
| 1 | **Text** | Paste your Import URL |
| 2 | **Set Variable** | Variable name: `BackendURL` (input: the Text above) |
| 3 | **Text** | Type `Bearer ` (with one space) then paste your token, e.g. `Bearer etk_AbC123…` |
| 4 | **Set Variable** | Variable name: `AuthHeader` |
| 5 | **Extract Text from Image** | Tap "Image" → choose **Shortcut Input** |
| 6 | **Get Contents of URL** | URL: tap → select variable **BackendURL**. Tap **›** (Show More): **Method** `POST` · **Headers** → Add new header: key `Authorization`, value → variable **AuthHeader**; add another: key `Content-Type`, value `application/json` · **Request Body** `JSON` → Add new field → **Text** → key `ocr_text`, value → select the magic variable **Text from Image** (output of step 5) |
| 7 | **Get Dictionary Value** | Get **Value** for key `message` in **Contents of URL** |
| 8 | **Show Notification** | Body: **Dictionary Value** (title optional: "Expense Tracker") |

Tap **Done**.

The finished Shortcut:

```
Receive Images from Share Sheet
Text  "https://YOUR-BACKEND.onrender.com/api/transactions/import/phonepe"
Set variable BackendURL
Text  "Bearer etk_…"
Set variable AuthHeader
Extract Text from Shortcut Input
Get Contents of BackendURL   (POST, JSON body: ocr_text = Text from Image)
Get Value for "message" in Contents of URL
Show Notification: Dictionary Value
```

The Shortcut doesn't parse anything. It sends the full OCR text, and the backend's `message` field is already a ready-to-show sentence:

| Backend status | Notification |
|---|---|
| `created` | `Expense added: ₹183 — BLINK COMMERCE PRIVA` |
| `duplicate` | `Transaction already exists` |
| `review_required` | `Transaction requires review. Open the Expense Tracker to confirm it.` |
| `invalid` | `Couldn't read a receipt from this image…` |

The first time it runs, iOS asks *"Allow Phonepay Automation to connect to …onrender.com?"*. Tap **Always Allow**.

To change servers later, edit only the Text in step 1. To rotate the token, create a new one in Settings, paste it into step 3, and delete the old one.

---

## 14. PhonePe import workflow

What happens when you share a receipt:

1. **Authenticate**: the `Authorization: Bearer etk_…` token is hashed and looked up. Unknown token → 401.
2. **Rate limit**: max 30 imports per minute per user (429 otherwise). Requests over 64 KB → 413.
3. **Parse** (`services/phonepe_parser.py`):
   - Cleans the text and finds label lines: *Paid to, Amount, Date, PhonePe Transaction ID, Debited from, UTR, UPI Ref, Message*. Each value is on the same line or within the next 3 lines.
   - Identifiers first (transaction ID, UTR, account, date and time). Their lines are then excluded, so **the amount is never taken from an ID, UTR, account number or date**.
   - Amount: the value after "Amount" (tolerating `₹ ¥ Rs INR`, misread symbols, inserted spaces, `1,25,000`). With no label, only numbers with an explicit currency marker count, and if several different ones appear it asks for review.
   - OCR fixes: `O`→`0` and `I/l`→`1` inside IDs, a leading `7`→`T` on transaction IDs, `0ct`→`Oct`, `2O26`→`2026`.
4. **Enrich**: bank from your Settings → Bank accounts mapping; category from your past choice for that merchant, otherwise from rules (`services/categorizer.py`).
5. **Duplicate check (strong)**: same PhonePe transaction ID or UTR/UPI ref → `duplicate`.
6. **AI fallback** (`services/llm_extractor.py`, only if `OPENAI_API_KEY` is set and the parser is missing the amount, merchant or date):
   - OpenAI gets a **redacted** copy: transaction IDs, UTRs and account numbers are replaced with placeholders, and the request is sent with `store=false`. IDs always come from the rule-based parser.
   - Its answer is **verified**: the amount must literally appear as a number in the receipt (and not be part of a date or time); if the parser saw several amounts, it must be one of them. The merchant's words must appear in the text.
   - The merged result is validated again. If anything is still uncertain, it goes to review. On timeout or API errors it also goes to review.
   - These transactions are marked **"Read by: AI-assisted"** on the detail page.
   - Cost: one short request (~1–4 s, a fraction of a cent) and **only** for receipts the parser couldn't read. Re-shared duplicates never call it.
7. **Validate**: anything uncertain (no amount, conflicting amounts, no merchant, no date, future date, money *received*, no ID and no UTR) → stored in `pending_imports` → `review_required`. **Nothing uncertain is saved as a transaction.**
8. **Duplicate check (fallback)**: same date + amount + merchant (+ account last 4 and time) → `duplicate`.
9. **Save**, with database unique constraints as the final guard against two identical requests at the same instant.
10. The raw OCR text is stored with the transaction for debugging (visible only to you, under "Debug details" on the transaction page). **It is never written to logs.**

### Reviewing

When an import needs review, the dashboard shows a yellow banner and **Import** lists it. Open it to see why it needs review (problem fields are highlighted), fix the values, and click **Save transaction**. If a very similar transaction already exists, you can view it or choose "save anyway". **Discard** throws the import away.

After a parser improvement, or after adding `OPENAI_API_KEY`, click **Retry all** on the Import page. Every pending import is run through the latest pipeline, and the ones that now read cleanly are saved automatically.

Sharing the same receipt again (even if the OCR text comes out slightly different) updates the same review instead of creating a second one, because reviews are matched by transaction ID/UTR as well as by text.

**Known limit:** if OCR turns ₹ into the digit `2` (₹183 → `2183`), the text really says 2183 and neither the parser nor the AI can know otherwise. Check amounts that look too large and edit them.

---

## 15. End-to-end test

### Locally (without an iPhone)

1. Start the backend and frontend (section 4) and register.
2. **Import** page → **Use sample receipt** → **Import** → *"Expense added: ₹183 — BLINK COMMERCE PRIVA"*.
3. Click **Import** again → *"Transaction already exists"*.
4. Dashboard: ₹183 under Groceries; Transactions: the row has a **PhonePe** badge.
5. Open it: transaction ID `T2610031311415776289288`, UTR `706226593892`, account `•••• 6929`. Raw OCR is under "Debug details".
6. Review flow: paste the sample with the `Amount:` lines deleted and a different transaction ID/UTR → you're taken to the review screen → enter the amount → save.

Simulating the Shortcut exactly, with curl (create a token in Settings first):

```bash
curl -X POST http://localhost:8000/api/transactions/import/phonepe \
  -H "Authorization: Bearer etk_YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ocr_text": "Paid to\nBLINK COMMERCE PRIVA...\n\nAmount:\n¥183\n\nDate:\n3 October 2026\n1:11 PM\n\nPhonePe Transaction ID:\nT2610031311415776289288\n\nDebited from:\nXXXXXX096929\n\nUTR:\n706226593892\n\nMessage:\nUPIIntent"}'
```

Expected (HTTP 201):

```json
{
  "success": true,
  "status": "created",
  "message": "Expense added: ₹183 — BLINK COMMERCE PRIVA",
  "transaction": {
    "amount": "183.00",
    "merchant_name": "BLINK COMMERCE PRIVA",
    "category": "Groceries",
    "phonepe_transaction_id": "T2610031311415776289288",
    "utr": "706226593892",
    "account_last4": "6929",
    "source": "phonepe"
  }
}
```

Run the same command again → HTTP 200, `"status": "duplicate"`.

> Amounts are returned as exact strings (`"183.00"`) rather than JSON numbers so no floating-point rounding can sneak in.

### In production (with your iPhone)

1. Open `https://YOUR-BACKEND.onrender.com/api/health` in Safari first to wake the server.
2. PhonePe → **History** → open a completed payment → **Share Receipt** → **Phonepay Automation**.
3. Notification: *"Expense added: ₹… — MERCHANT"*.
4. Share the same receipt again → *"Transaction already exists"*.
5. Open the web app: the transaction is on the dashboard with a PhonePe badge.

---

## 16. Troubleshooting

| Problem | Fix |
|---|---|
| **Shortcut shows nothing, or an error, the first time in a while** | The free Render server was asleep (it sleeps after 15 min idle; waking takes 30–60 s, and the Shortcut may time out). Run it again. To avoid this, use a free uptime pinger (e.g. cron-job.org or UptimeRobot) to request `/api/health` every 10–14 minutes, or upgrade the Render instance. |
| Shortcut notification: "Invalid import token" | The token was deleted or mistyped. Create a new one in Settings; the header value must be `Bearer etk_…` with a space after Bearer. |
| Shortcut: "Get Dictionary Value" fails | The server didn't return JSON (usually it was still waking up, or the URL is wrong). Check the URL ends in `/api/transactions/import/phonepe`. |
| Receipts go to review with "Amount could not be found" | Set `OPENAI_API_KEY` on Render (the AI fallback reads unusual ₹ misreads), then click **Retry all** on the Import page. If one still fails, open it, expand **Raw OCR text**, and add that text as a test case in `tests/test_llm_fallback.py`. |
| Imports marked AI-assisted are wrong | Edit them, and consider a different `OPENAI_MODEL`. Remove `OPENAI_API_KEY` (or set `LLM_FALLBACK_ENABLED=false`) to always use manual review instead. |
| Log shows `LLM fallback failed: AuthenticationError` / `RateLimitError` | The OpenAI key is wrong or revoked, or the account has no credit. Imports keep working; they go to review. |
| Every receipt goes to review | Open the review and expand **Raw OCR text** to see what the iPhone extracted. If PhonePe changed its layout, update the label patterns in `phonepe_parser.py`, add the text as a test in `tests/test_phonepe_parser.py`, and redeploy. |
| Frontend: "Can't reach the server" | `VITE_API_URL` is wrong or the backend is asleep. Changing `VITE_API_URL` requires redeploying the static site. |
| Browser console: CORS error | `CORS_ORIGINS` on the backend must exactly match the frontend URL (`https://…onrender.com`, no trailing slash). |
| Refreshing a page on Render shows "Not Found" | Add the static-site rewrite `/*` → `/index.html` (included in `render.yaml`). |
| Render deploy fails: `JWT_SECRET must be at least 32 characters` | Set a longer secret. |
| Render deploy fails: database connection timeout / "Network is unreachable" | You used Supabase's *Direct connection* (IPv6). Use the **Session pooler** URI. |
| `password authentication failed` | Wrong DB password, or special characters not URL-encoded. |
| Supabase "project paused" | Free projects pause after 7 days without activity. Restore it from the Supabase dashboard. |
| Today's total looks wrong | Check `APP_TIMEZONE` (default `Asia/Kolkata`). |
| "Registration is disabled" | `ALLOW_REGISTRATION=false` is working as intended. Set it to `true` temporarily if you need another account. |
| Local `pip install` fails building `pydantic-core` | Your Python is newer than the pinned packages support. Use the versions in `requirements.txt` (they support 3.12–3.14) or Python 3.13. |

---

## 17. API reference

All endpoints are under `/api`. Everything except `health`, `meta`, `register` and `login` needs `Authorization: Bearer <JWT>`. The PhonePe import also accepts an import token.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check (also checks the database) |
| GET | `/meta` | Categories, payment methods, whether registration is open |
| POST | `/auth/register` | `{email, password, full_name?}` → `{access_token, user}` |
| POST | `/auth/login` | `{email, password}` → `{access_token, user}` |
| GET | `/auth/me` | Current user |
| GET | `/transactions` | List. Filters: `date, date_from, date_to, month, year, category, bank, payment_method, merchant, search, min_amount, max_amount, source`; `sort_by` (date/amount/merchant/category/created), `sort_order`, `page`, `page_size` (max 100) |
| GET | `/transactions/filter-options` | Values for filter dropdowns |
| GET | `/transactions/{id}` | One transaction (includes `raw_ocr_text`) |
| POST | `/transactions` | Create (manual) |
| PUT | `/transactions/{id}` | Update (send only the fields you change) |
| DELETE | `/transactions/{id}` | Delete → 204 |
| POST | `/transactions/import/phonepe` | `{ocr_text}` → `created` 201 / `duplicate` 200 / `review_required` 202 / `invalid` 422 |
| GET | `/imports/pending` | Imports waiting for review |
| POST | `/imports/pending/reprocess` | Re-run all pending imports through the latest parser + AI fallback → `{created, duplicate, review_required, invalid}` |
| GET | `/imports/pending/{id}` | One pending import (with raw text) |
| POST | `/imports/pending/{id}/confirm` | Save the reviewed transaction (`?allow_similar=true` to bypass the fallback duplicate check) |
| DELETE | `/imports/pending/{id}` | Discard |
| GET | `/stats/dashboard?year=&month=` | All dashboard numbers |
| GET/POST/DELETE | `/settings/tokens[/{id}]` | Manage import tokens |
| GET/POST/DELETE | `/settings/accounts[/{id}]` | Manage account → bank mappings |

Error responses always look like `{"detail": "Human readable message"}` (422s also include `errors: [{field, message}]`). Status codes: 400, 401, 403, 404, 409 (duplicate), 413, 422, 429, 500. Stack traces are never sent to clients.

---

## 18. Extending: new import sources

The import pipeline doesn't depend on PhonePe:

```
services/
  parsing.py              # ParsedTransaction + ParseResult: the common format
  phonepe_parser.py       # PhonePe receipt OCR → ParseResult
  llm_extractor.py        # optional AI fallback (redacted input, verified output)
  transaction_importer.py # generic pipeline + PARSERS registry
  categorizer.py          # merchant → category rules
  duplicate_detector.py   # ID/UTR + fallback duplicate checks
```

To add, say, Google Pay receipts or bank SMS text:

1. Add `SOURCE_GPAY = "gpay"` to `core/constants.py` (and to `SOURCES`).
2. Write `services/gpay_parser.py` with `parse_gpay_receipt(text, today) -> ParseResult`.
3. Register it: `PARSERS[SOURCE_GPAY] = parse_gpay_receipt` in `transaction_importer.py`.
4. Add an endpoint in `api/imports.py` that calls `transaction_importer.import_text(db, user.id, SOURCE_GPAY, text, today_local())`.
5. Add tests.

CSV or PDF bank statements produce many transactions per file: loop over the rows and call the same duplicate detector and `transaction_service.create_transaction` for each one.
