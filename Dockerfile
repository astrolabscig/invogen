FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# WeasyPrint's native rendering deps (Pango/cairo/gdk-pixbuf), not Python
# packages — pip can't install these, and importing weasyprint without them
# crashes at PDF-render time, not at container start.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev \
      libcairo2 shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Requirements copied and installed before the rest of the app, so this layer
# only rebuilds when requirements.txt actually changes, not on every code edit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# collectstatic imports config/settings.py, which does SECRET_KEY =
# os.environ['SECRET_KEY'] with no fallback — it needs *a* value to import,
# not a real one, since collectstatic only touches STATIC_ROOT, never the
# DB or anything secret-dependent. This ARG is build-scope only: it's never
# written to an ENV layer, so it doesn't persist into the image or leak via
# `docker inspect`, and it plays no part at container runtime — Railway
# injects the real SECRET_KEY as a runtime env var when gunicorn starts.
ARG SECRET_KEY=build-time-placeholder-unused-at-runtime
RUN SECRET_KEY=$SECRET_KEY python manage.py collectstatic --noinput

# Migrations run as a Railway release step, not at image build time, so a
# stale image never runs a half-applied migration against the live DB.

CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3"]
