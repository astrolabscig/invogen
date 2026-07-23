# Invogen

A single-user-per-account invoicing tool for solo freelancers. Each user manages their own clients and issues invoices to them. 

## Stack
- Django 5.2 LTS
- SQLite (local development)
- Django Templates
- Python 3.12+

## Setup Instructions

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

4. **Environment Variables**
   Create a `.env` file in the root directory based on `.env.example`:
   ```bash
   cp .env.example .env
   ```
   Add your `SECRET_KEY` and set `DEBUG=True` for local development.

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

## Design Decisions

- **Why Invoice total is stored rather than dynamically computed:** An issued invoice is an immutable financial record. Once its status moves to SENT or PAID, the total is frozen and must never change, even if line item historical rates adjust.
- **Why Client FK uses PROTECT:** Deleting a client who has existing invoices must fail loudly to preserve the integrity of past financial records. Line items, however, cascade with the invoice.
- **Why money fields use Decimal rather than Float:** Binary floats cannot represent currency exactness (e.g., 0.1 + 0.2 = 0.30000000000000004 in floating point arithmetic). `DecimalField` is strictly used for all monetary and quantity values to ensure perfect accuracy.
