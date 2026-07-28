import datetime
import uuid
from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import models
from django.contrib.auth.models import User


class Currency(models.TextChoices):
    # Left value is the ISO 4217 code Paystack expects, so the same stored
    # value drives both display and the Paystack currency param.
    GHS = "GHS", "Ghanaian Cedi (GH₵)"
    NGN = "NGN", "Nigerian Naira (₦)"
    USD = "USD", "US Dollar ($)"


# Single source of truth for currency->symbol, used by Client.get_currency_symbol()
# and Invoice.get_currency_symbol() so templates/PDF never hardcode symbols themselves.
CURRENCY_SYMBOLS = {
    Currency.GHS: "GH₵",
    Currency.NGN: "₦",
    Currency.USD: "$",
}


class Client(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='clients')
    name = models.CharField(max_length=200)
    email = models.EmailField()
    company = models.CharField(max_length=200, blank=True)
    address = models.TextField(blank=True)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.GHS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['owner', 'email'], name='unique_client_email_per_owner')
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Single point of truth for the normalization, so it applies no
        # matter how a Client is saved (form, admin, shell) — not just the
        # form path, which also checks this early for a friendly error.
        self.email = self.email.lower()
        super().save(*args, **kwargs)

    def get_currency_symbol(self):
        return CURRENCY_SYMBOLS[self.currency]


class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SENT = 'SENT', 'Sent'
        PAID = 'PAID', 'Paid'

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invoices')
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='invoices')
    # Public, unguessable identifier for the client-facing invoice/checkout URLs
    # (no login for clients), so we don't expose the sequential pk.
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    # Auto-assigned per-owner sequentially at creation (see next_number_for);
    # editable=False keeps it out of ModelForms so it can't be typed or
    # edited even if a form/admin accidentally adds it back.
    number = models.CharField(max_length=20, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    issue_date = models.DateField(default=datetime.date.today)
    due_date = models.DateField(null=True, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    # Frozen copy of client.currency at creation time (see Invoice.get_currency_symbol
    # and InvoiceCreateView) — not read live from the client, so changing a client's
    # currency later can't retroactively change what an existing invoice was billed in.
    # Same principle as `total`.
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.GHS)
    notes = models.TextField(blank=True)
    pdf = models.FileField(upload_to='invoices/%Y/%m/', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['owner', 'number'], name='unique_invoice_number_per_owner')
        ]

    def __str__(self):
        return f"{self.number} ({self.client.name})"

    @staticmethod
    def next_number_for(owner):
        """Computes the next per-owner sequential invoice number
        ("INV-0001", "INV-0002", ...).

        MUST be called inside an already-open transaction.atomic() block,
        immediately before creating and saving the new Invoice, in the same
        transaction. select_for_update() locks the owner's existing invoice
        rows on backends that support row locking (Postgres, MySQL/InnoDB):
        a second concurrent call for the same owner blocks on that lock
        until the first transaction commits (or rolls back), so it can never
        read the same "current max" and compute a colliding number. SQLite
        (used in dev here) doesn't support SELECT ... FOR UPDATE, so on it
        this call degrades to a plain read with no locking — the
        UniqueConstraint('owner', 'number') is the backstop for that case
        (and for the brief unlocked window before an owner's very first
        invoice exists, since there's nothing yet to lock).
        """
        numbers = (
            Invoice.objects.select_for_update()
            .filter(owner=owner)
            .values_list('number', flat=True)
        )
        max_seq = 0
        for number in numbers:
            try:
                seq = int(number.rsplit('-', 1)[-1])
            except (ValueError, IndexError):
                continue
            max_seq = max(max_seq, seq)
        return f"INV-{max_seq + 1:04d}"

    def get_currency_symbol(self):
        return CURRENCY_SYMBOLS[self.currency]

    def recalculate_total(self):
        """Recalculates total from LineItems."""
        if self.pk:
            self.total = sum((item.subtotal for item in self.items.all()), Decimal('0.00'))
        else:
            self.total = Decimal('0.00')

    def save(self, *args, **kwargs):
        if self.status == self.Status.DRAFT:
            self.recalculate_total()
        super().save(*args, **kwargs)


class Payment(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='payments')
    reference = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    channel = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=20)
    raw_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.reference} ({self.status})"


class LineItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
    )

    @property
    def subtotal(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return self.description
