"""Standalone currency converter — a draft-time calculator only.

Deliberately isolated from invoices/payments: this module imports no
Invoice/Payment/Client and writes nothing to any model. Kept in its own
file (not billing/services.py) to make that isolation visible at a glance.
"""
from decimal import Decimal

import requests
from django.core.cache import cache

FX_API_URL = 'https://open.er-api.com/v6/latest/{base}'
# Rates change daily, not per-request — refetching every request just burns
# the free-tier quota for no benefit.
CACHE_TIMEOUT = 60 * 60


def _fetch_rates(base):
    cache_key = f"fx_rates_{base}"
    data = cache.get(cache_key)
    if data is not None:
        return data

    try:
        response = requests.get(FX_API_URL.format(base=base), timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        raise ValueError("Exchange rate unavailable right now.") from e

    cache.set(cache_key, data, CACHE_TIMEOUT)
    return data


def _extract_rate(data, target):
    try:
        # API returns a float; str() first so we never contaminate Decimal
        # money math with binary float imprecision.
        return Decimal(str(data["rates"][target]))
    except (KeyError, TypeError) as e:
        raise ValueError("Exchange rate unavailable right now.") from e


def get_exchange_rate(base: str, target: str) -> Decimal:
    data = _fetch_rates(base)
    return _extract_rate(data, target)


def convert(amount: Decimal, base: str, target: str) -> dict:
    data = _fetch_rates(base)
    rate = _extract_rate(data, target)
    return {
        "amount": amount,
        "base": base,
        "target": target,
        "rate": rate,
        "result": (amount * rate).quantize(Decimal("0.01")),
        "as_of": data.get("time_last_update_utc"),
    }
