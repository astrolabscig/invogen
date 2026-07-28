from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client as HttpClient
from django.urls import reverse

from .models import Client, Invoice, LineItem


class InvoiceTotalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='pass12345')
        self.client_obj = Client.objects.create(
            owner=self.user, name='Acme', email='a@acme.test'
        )

    def test_draft_total_recalculates_from_line_items(self):
        invoice = Invoice.objects.create(
            owner=self.user,
            client=self.client_obj,
            number='INV-1',
            status=Invoice.Status.DRAFT,
        )
        LineItem.objects.create(
            invoice=invoice, description='Work', quantity=Decimal('2'), unit_price=Decimal('50.00')
        )
        LineItem.objects.create(
            invoice=invoice, description='More', quantity=Decimal('1'), unit_price=Decimal('25.50')
        )
        invoice.save()
        invoice.refresh_from_db()
        self.assertEqual(invoice.total, Decimal('125.50'))

    def test_sent_total_does_not_recalculate(self):
        invoice = Invoice.objects.create(
            owner=self.user,
            client=self.client_obj,
            number='INV-2',
            status=Invoice.Status.DRAFT,
        )
        LineItem.objects.create(
            invoice=invoice, description='Work', quantity=Decimal('1'), unit_price=Decimal('100.00')
        )
        invoice.save()
        invoice.refresh_from_db()
        self.assertEqual(invoice.total, Decimal('100.00'))

        invoice.status = Invoice.Status.SENT
        invoice.save()
        LineItem.objects.create(
            invoice=invoice, description='Should not affect total', quantity=Decimal('1'), unit_price=Decimal('999.00')
        )
        invoice.save()
        invoice.refresh_from_db()
        self.assertEqual(invoice.total, Decimal('100.00'))


class OwnershipAndStatusTests(TestCase):
    def setUp(self):
        self.http = HttpClient()
        self.owner = User.objects.create_user(username='owner', password='pass12345')
        self.other = User.objects.create_user(username='other', password='pass12345')
        self.client_obj = Client.objects.create(
            owner=self.owner, name='Acme', email='a@acme.test'
        )
        self.invoice = Invoice.objects.create(
            owner=self.owner,
            client=self.client_obj,
            number='INV-10',
            status=Invoice.Status.DRAFT,
        )
        LineItem.objects.create(
            invoice=self.invoice, description='Work', quantity=Decimal('1'), unit_price=Decimal('40.00')
        )
        self.invoice.save()

    def test_other_user_cannot_view_invoice(self):
        self.http.login(username='other', password='pass12345')
        response = self.http.get(reverse('invoice_detail', kwargs={'pk': self.invoice.pk}))
        self.assertEqual(response.status_code, 404)

    def test_status_update_rejects_draft_to_sent(self):
        # DRAFT->SENT no longer goes through this view at all: it only
        # happens via InvoiceSendView (billing/views.py), which generates
        # the PDF, emails the client, and freezes the total.
        self.http.login(username='owner', password='pass12345')
        response = self.http.post(
            reverse('invoice_status_update', kwargs={'pk': self.invoice.pk, 'new_status': 'sent'})
        )
        self.assertEqual(response.status_code, 400)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.DRAFT)

    def test_status_transition_sent_to_paid(self):
        self.invoice.status = Invoice.Status.SENT
        self.invoice.save()

        self.http.login(username='owner', password='pass12345')
        r2 = self.http.post(
            reverse('invoice_status_update', kwargs={'pk': self.invoice.pk, 'new_status': 'paid'})
        )
        self.assertEqual(r2.status_code, 302)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)

    def test_invalid_status_transition_rejected(self):
        self.http.login(username='owner', password='pass12345')
        response = self.http.post(
            reverse('invoice_status_update', kwargs={'pk': self.invoice.pk, 'new_status': 'paid'})
        )
        self.assertEqual(response.status_code, 400)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.DRAFT)
