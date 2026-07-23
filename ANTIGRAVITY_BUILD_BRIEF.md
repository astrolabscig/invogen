# Build Brief — Freelance Invoice Manager (Django)


---

## Context

A single-user-per-account invoicing tool for solo freelancers. Each user manages their own
clients and issues invoices to them. Build the full working application.

**Stack (fixed — do not substitute):**
- Django 5.2 LTS
- SQLite for local development
- Django templates for the frontend, server-rendered. No SPA, no JS framework.
- Python 3.12+

Prioritise correctness and security over feature count.

---

## Data model

### Client
| Field | Type | Notes |
|---|---|---|
| owner | FK → User | `on_delete=CASCADE`, `related_name='clients'` |
| name | CharField(200) | required |
| email | EmailField | required |
| company | CharField(200) | blank allowed |
| address | TextField | blank allowed |
| created_at | DateTimeField | `auto_now_add=True` |

### Invoice
| Field | Type | Notes |
|---|---|---|
| owner | FK → User | `on_delete=CASCADE`, `related_name='invoices'` |
| client | FK → Client | `on_delete=PROTECT`, `related_name='invoices'` |
| number | CharField(20) | unique **per owner** — see constraints |
| status | CharField(10) | use `TextChoices`: DRAFT / SENT / PAID |
| issue_date | DateField | defaults to today |
| due_date | DateField | |
| total | DecimalField(12, 2) | **stored**, see rules below |
| notes | TextField | blank allowed |
| created_at | DateTimeField | `auto_now_add=True` |
| updated_at | DateTimeField | `auto_now=True` |

### LineItem
| Field | Type | Notes |
|---|---|---|
| invoice | FK → Invoice | `on_delete=CASCADE`, `related_name='items'` |
| description | CharField(255) | required |
| quantity | DecimalField(10, 2) | allows fractional hours |
| unit_price | DecimalField(12, 2) | |

`subtotal` is a **computed property** on LineItem (`quantity * unit_price`). Never stored.

---

## Non-negotiable rules

These are correctness and security requirements. Do not deviate.

1. **Every money and quantity field is `DecimalField`. Never `FloatField`.** Binary floats
   cannot represent currency exactly.
2. **Every queryset in every view is filtered by `request.user`.** No exceptions. A user must
   never be able to read, edit, or delete another user's client or invoice, including by
   guessing an ID in the URL.
3. `Invoice.client` uses `on_delete=PROTECT` — deleting a client with invoices must fail loudly.
   `LineItem.invoice` uses `on_delete=CASCADE` — line items die with their invoice.
4. Invoice number is unique **per owner**, via a `Meta` constraint:
   `UniqueConstraint(fields=['owner', 'number'], name='unique_invoice_number_per_owner')`.
   Do **not** put `unique=True` on the field — that would make numbers globally unique.
5. `Invoice.total` is a stored column. Recalculate it from the line items on save **only while
   `status == DRAFT`**. Once status moves to SENT or PAID the total is frozen and must not
   change, even if line items are edited. An issued invoice is a financial record.
6. `status` uses `models.TextChoices`, not bare strings.
7. Saving an invoice together with its line items happens inside `transaction.atomic()`.
8. Status transitions are guarded: DRAFT → SENT → PAID only. Reject any other transition
   (no jumping DRAFT → PAID, no reverting PAID → DRAFT).
9. `SECRET_KEY` and `DEBUG` are read from environment variables via a `.env` file.
   Nothing secret is hardcoded or committed. Include `.env` in `.gitignore`.
10. All forms use `{% csrf_token %}`.

---

## Features

1. **Auth** — register, login, logout. Every business view requires login.
2. **Client CRUD** — list, create, edit, delete.
3. **Invoice create** — one page, with an inline formset for line items so multiple items can
   be added on the same form.
4. **Invoice list / detail / edit / delete** — list uses `select_related('client')` to avoid
   an N+1 query.
5. **Status actions** — "Mark as sent" and "Mark as paid" buttons, with the transition rules
   in #8 enforced server-side.
6. **Dashboard** — total outstanding (sum of SENT invoices), total paid, and the five most
   recent invoices. Use ORM aggregation, not Python loops.

---

## Deliverables

- Working app; `python manage.py runserver` starts clean with no warnings
- `requirements.txt`
- `README.md` with setup and run instructions
- A seed script (`python manage.py seed_demo`) creating one demo user, 3 clients and
  5 invoices across all three statuses
- Clean, readable templates — plain semantic HTML with minimal CSS is fine

---

## Explicitly out of scope

Do not add any of these. They will burn time and add nothing here.

- Django REST Framework, Celery, Redis, Docker, Channels
- Any JavaScript framework
- PDF generation, payment integration, email sending
- A test suite beyond one smoke test that the homepage returns 200

---

## Verification checklist

Before you report the task complete, verify each of these in the browser and confirm:

- [ ] Register two separate users, A and B
- [ ] As A, create a client and an invoice; note the invoice's URL and ID
- [ ] Log in as B and open A's invoice URL directly — **must return 404 or 403, never the invoice**
- [ ] As B, attempt to open A's client edit URL — must be blocked
- [ ] Create an invoice with 3 line items; confirm the total matches manual arithmetic
- [ ] Mark it sent, then edit a line item — confirm the stored total does **not** change
- [ ] Attempt to mark a DRAFT invoice as paid directly — must be rejected
- [ ] Confirm `grep -r "FloatField" .` returns nothing
- [ ] Confirm `grep -rn "SECRET_KEY" settings.py` shows it read from the environment
