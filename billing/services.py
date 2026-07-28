import re
from decimal import Decimal
from uuid import uuid4

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse

from .models import Invoice

PAYSTACK_INITIALIZE_URL = 'https://api.paystack.co/transaction/initialize'
# Paystack transaction references may only contain alphanumerics, '-', '.', '='.
_REFERENCE_UNSAFE_CHARS = re.compile(r'[^A-Za-z0-9\-.=]')


def render_invoice_pdf(invoice):
    """Renders an Invoice to PDF bytes. Pure render: does not save anything
    or touch invoice.status."""
    # Imported here, not at module level: WeasyPrint needs native GTK libs
    # (Pango/cairo/gobject) that may be absent on a given machine, and importing
    # it at module scope would crash the whole app (views.py imports this
    # module) rather than failing only when a PDF is actually requested.
    from weasyprint import HTML

    html_string = render_to_string('billing/invoice_pdf.html', {'invoice': invoice})
    # No request is available here, so static/media refs resolve against
    # BASE_DIR on disk rather than over HTTP.
    base_url = f'file://{settings.BASE_DIR}/'
    return HTML(string=html_string, base_url=base_url).write_pdf()


def send_invoice(invoice):
    """Freezes the invoice total, renders and saves its PDF, and marks it
    SENT — all in one DB transaction. The confirmation email is sent only
    after that transaction commits, since an email can't be rolled back:
    sending it inside the block could leave the client holding an email for
    an invoice the DB then discarded."""
    if invoice.status != Invoice.Status.DRAFT:
        raise ValueError("Only draft invoices can be sent.")

    with transaction.atomic():
        invoice.recalculate_total()
        pdf_bytes = render_invoice_pdf(invoice)
        # save=False: the file path is persisted by invoice.save() below,
        # so the PDF assignment and status change land in one DB write.
        invoice.pdf.save(f"invoice-{invoice.number}.pdf", ContentFile(pdf_bytes), save=False)
        invoice.status = Invoice.Status.SENT
        invoice.save()

    send_invoice_email(invoice)


def send_invoice_email(invoice):
    """Emails the invoice PDF to the client. Assumes invoice.pdf is already
    saved; call only after send_invoice's transaction has committed."""
    owner_name = invoice.owner.get_full_name() or invoice.owner.username
    email = EmailMessage(
        subject=f"Invoice {invoice.number} from {owner_name}",
        body=f"Please find attached invoice {invoice.number}.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[invoice.client.email],
    )
    with invoice.pdf.open('rb') as pdf_file:
        email.attach(f"invoice-{invoice.number}.pdf", pdf_file.read(), 'application/pdf')
    email.send()


def initialize_payment(invoice, request):
    """Starts a Paystack transaction for invoice and returns the
    authorization_url the client should be redirected to for checkout.

    Payment to invoice is correlated via metadata, not a stored pending row:
    a Payment row is only ever created on a real charge.success (see the
    webhook), so the unique Paystack reference gives idempotency naturally
    without needing a pending-state row here."""
    if invoice.status != Invoice.Status.SENT:
        raise ValueError("Only sent invoices can be paid online.")

    # Paystack account constraint: this account can only charge GHS today,
    # even though the model supports more currencies.
    if invoice.currency != "GHS":
        raise ValueError("Online payment is currently only available for GHS invoices.")

    # GHS subunit = pesewas = total * 100. Decimal only, never float.
    amount_subunit = int((invoice.total * Decimal("100")).to_integral_value())

    safe_number = _REFERENCE_UNSAFE_CHARS.sub('', invoice.number)
    reference = f"INV-{safe_number}-{uuid4().hex[:10]}"

    callback_url = request.build_absolute_uri(
        reverse('public_invoice', kwargs={'token': invoice.token})
    )

    try:
        response = requests.post(
            PAYSTACK_INITIALIZE_URL,
            headers={
                'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'email': invoice.client.email,
                'amount': amount_subunit,
                # Explicit — Paystack defaults to NGN otherwise.
                'currency': invoice.currency,
                'reference': reference,
                'callback_url': callback_url,
                'metadata': {'invoice_token': str(invoice.token)},
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        raise ValueError("Could not reach Paystack. Please try again shortly.") from e

    # Paystack's top-level "status" is whether the API call succeeded, NOT
    # whether the payment succeeded.
    if not data.get('status'):
        raise ValueError(data.get('message') or "Paystack could not initialize this payment.")

    return data['data']['authorization_url']
