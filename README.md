# Invogen

A single-user-per-account invoicing tool for solo freelancers. Each user manages their own clients, issues itemized invoices, sends them by email with an attached PDF, and can accept online payment via Paystack.

## Stack
- Django 5.2 LTS
- SQLite (local development) / PostgreSQL via `DATABASE_URL` (production)
- Django Templates
- WeasyPrint (PDF rendering)
- Paystack (payment initialization + webhook)
- Gunicorn + WhiteNoise (production serving), Docker
- Python 3.12+

## Core Features

- **Multi-tenant clients & invoices** — every client, invoice, and line item is scoped to the logged-in user (`request.user`); one user can never view or act on another's data.
- **Draft invoice builder** — inline line-item formset; the total recalculates from line items automatically while the invoice is `DRAFT`, and freezes the moment it becomes `SENT`/`PAID`.
- **Auto-numbered invoices** — numbers (`INV-0001`, `INV-0002`, ...) are assigned automatically per owner at creation, never typed by hand.
- **Per-client/invoice currency** — each client has a currency (GHS/NGN/USD); a new invoice freezes a copy of its client's currency at creation time, so changing a client's currency later never rewrites an already-issued invoice.
- **Send flow** — sending a `DRAFT` invoice (`InvoiceSendView`) freezes the total, renders a PDF, marks it `SENT`, and emails the PDF to the client — all inside one transaction, with the email sent only after that transaction commits.
- **Online payment (Paystack, GHS only for now)** — a client can open their invoice via an unguessable per-invoice link (no login required) and pay online. The Paystack webhook, not the browser redirect back from checkout, is the sole source of truth for marking an invoice `PAID`: it verifies the HMAC signature over the raw request body, re-checks amount and currency server-side, and is idempotent via a unique payment reference.
- **Currency converter tool** — a standalone, login-only utility for a quick indicative FX estimate while drafting a price. Deliberately isolated from the invoice/payment models — it never writes anything and never claims to preview Paystack's actual settlement rate.
- **Status state machine** — `DRAFT → SENT → PAID` only; skipping or reversing states is rejected server-side with `400`, not just hidden in the UI.

## Setup Instructions (local development)

1. **Clone the repository**
   ```bash
   git clone https://github.com/astrolabscig/invogen.git
   cd invogen
   ```

2. **Create and activate a virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
   WeasyPrint (PDF rendering) needs native libraries (Pango, cairo, GDK-Pixbuf) that aren't installed by pip. If PDF rendering/sending fails locally with an `OSError` about a missing library, follow WeasyPrint's [installation guide](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation) for your OS — everything else in the app works without it.

4. **Environment Variables**
   Create a `.env` file in the root directory based on `.env.example`:
   ```bash
   cp .env.example .env
   ```
   At minimum, set `SECRET_KEY` and keep `DEBUG=True` for local development. See [Environment Variables](#environment-variables) below for what everything else does.

5. **Run migrations**
   ```bash
   python manage.py migrate
   ```

6. **Seed the database with demo data**
   ```bash
   python manage.py seed_demo
   ```
   *(This creates a demo user with username `demo` and password `demo12345`, plus some sample clients and invoices)*

7. **Run the development server**
   ```bash
   python manage.py runserver
   ```

8. **Run tests**
   ```bash
   python manage.py test billing
   ```

## Environment Variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SECRET_KEY` | **Yes** | — (crashes if unset) | Django's cryptographic secret. |
| `DEBUG` | No | `False` | `True` only for local dev — never in production. |
| `ALLOWED_HOSTS` | No | `localhost,127.0.0.1` | Comma-separated hostnames. Set to your real domain in production. |
| `CSRF_TRUSTED_ORIGINS` | No | *(empty)* | Comma-separated origins with scheme (`https://...`); needed in production so forms and the Paystack webhook aren't rejected. |
| `DATABASE_URL` | No | *(unset → SQLite)* | A Postgres URL in production (e.g. Railway injects this automatically); local dev stays on SQLite when unset. |
| `DEFAULT_FROM_EMAIL` | No | `invoices@example.com` | From-address on sent invoice emails. |
| `EMAIL_HOST` | No | *(unset → console backend)* | Setting this switches from printing emails to the terminal to sending real SMTP — no code change needed. |
| `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | No | dev-safe defaults | SMTP connection details, only relevant once `EMAIL_HOST` is set. |
| `PAYSTACK_SECRET_KEY` | For payments | *(unset → payment init fails, webhook returns 503)* | Server-side Paystack key — never exposed to the client. |
| `PAYSTACK_PUBLIC_KEY` | For payments | *(unset)* | Paystack public key. |

## Deployment (Docker / Railway)

A production `Dockerfile` is included (Python 3.12-slim, WeasyPrint's system libraries, Gunicorn). Static files are collected at build time and served via WhiteNoise; database migrations are **not** run in the image — run `python manage.py migrate` as a separate release step against the target database. The Paystack webhook must be registered at `<your-domain>/webhooks/paystack/`.

## Design Decisions

- **Why Invoice total is stored rather than dynamically computed:** An issued invoice is an immutable financial record. Once its status moves to `SENT` or `PAID`, the total is frozen and must never change, even if line item historical rates adjust.
- **Why Client FK uses PROTECT:** Deleting a client who has existing invoices must fail loudly to preserve the integrity of past financial records. Line items, however, cascade with the invoice.
- **Why money fields use Decimal rather than Float:** Binary floats cannot represent currency exactness (e.g., 0.1 + 0.2 = 0.30000000000000004 in floating point arithmetic). `DecimalField` is strictly used for all monetary and quantity values to ensure perfect accuracy.
- **Why invoice.currency is a frozen copy of client.currency, not a live lookup:** Same reasoning as total freezing — an issued invoice records what a client was billed in *at the time*. Changing a client's currency later must never retroactively change what an existing invoice says.
- **Why invoice numbering uses `select_for_update` inside the creation transaction:** Two concurrent invoice creations for the same owner must never compute the same "next number." Locking the owner's existing invoice rows for the duration of the transaction (on databases that support row locking) forces the second create to wait for the first to commit before it can read the true current max. The `UniqueConstraint(owner, number)` remains the final backstop everywhere, including on databases without row-level locking.
- **Why the email send happens outside the DB transaction:** `send_invoice()` freezes the total, renders the PDF, and marks the invoice `SENT` inside one `transaction.atomic()` block, then sends the email only after that block has committed. An email can't be rolled back — sending it inside the transaction risks the client holding an email for an invoice the database then discarded.
- **Why the Paystack webhook — not the browser checkout callback — marks invoices paid:** A client landing back on the invoice page after checkout proves nothing about whether the charge actually succeeded; browsers can be closed, redirects can fail, and the callback URL is not authenticated. Only the webhook, verified via HMAC signature over the raw request body, is treated as truth. It re-checks amount and currency itself rather than trusting the client-visible total, and creates `Payment` rows keyed on a unique reference so retried webhook deliveries can never double-process a charge.
- **Why the currency converter is a separate module (`billing/fx.py`), not part of `services.py`:** It's a draft-time pricing estimate only — it imports no invoice/payment/client models and writes nothing to the database. Keeping it physically separate makes that isolation obvious rather than relying on discipline within a shared file.
