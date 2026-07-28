import hashlib
import hmac
import json
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, View, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.db.models import Sum, Count, Q, Prefetch
from django.db.models.deletion import ProtectedError
from django.http import HttpResponseBadRequest, HttpResponse
from django.contrib.auth.forms import UserCreationForm

from .models import Invoice, LineItem, Client, Currency, Payment
from .forms import InvoiceForm, LineItemFormSet, ClientForm
from .services import render_invoice_pdf, send_invoice, initialize_payment
from . import fx

logger = logging.getLogger(__name__)


class RegisterView(CreateView):
    form_class = UserCreationForm
    template_name = 'registration/register.html'
    success_url = reverse_lazy('login')

class ClientOwnershipMixin(LoginRequiredMixin):
    def get_queryset(self):
        return Client.objects.filter(owner=self.request.user)

class InvoiceOwnershipMixin(LoginRequiredMixin):
    def get_queryset(self):
        return Invoice.objects.filter(owner=self.request.user)

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'billing/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_invoices = Invoice.objects.filter(owner=self.request.user)
        
        stats = user_invoices.aggregate(
            total_outstanding=Sum('total', filter=Q(status=Invoice.Status.SENT)),
            total_paid=Sum('total', filter=Q(status=Invoice.Status.PAID)),
            draft_count=Count('id', filter=Q(status=Invoice.Status.DRAFT))
        )
        
        client_count = Client.objects.filter(owner=self.request.user).count()
        recent_invoices = user_invoices.select_related('client').order_by('-created_at')[:5]
        
        context.update({
            'total_outstanding': stats['total_outstanding'] or 0,
            'total_paid': stats['total_paid'] or 0,
            'draft_count': stats['draft_count'] or 0,
            'client_count': client_count,
            'recent_invoices': recent_invoices,
        })
        return context

class ClientListView(ClientOwnershipMixin, ListView):
    model = Client
    template_name = 'billing/client_list.html'
    context_object_name = 'clients'

class ClientCreateView(ClientOwnershipMixin, CreateView):
    model = Client
    form_class = ClientForm
    template_name = 'billing/client_form.html'
    success_url = reverse_lazy('client_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.owner = self.request.user
        try:
            return super().form_valid(form)
        except IntegrityError:
            # Belt-and-suspenders for a race between clean_email's check and
            # the save: the DB constraint is the real guarantee.
            form.add_error('email', "You already have a client with this email.")
            return self.form_invalid(form)

class ClientUpdateView(ClientOwnershipMixin, UpdateView):
    model = Client
    form_class = ClientForm
    template_name = 'billing/client_form.html'
    success_url = reverse_lazy('client_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except IntegrityError:
            form.add_error('email', "You already have a client with this email.")
            return self.form_invalid(form)

class ClientDeleteView(ClientOwnershipMixin, DeleteView):
    model = Client
    template_name = 'billing/client_confirm_delete.html'
    success_url = reverse_lazy('client_list')

    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                f"Can't delete {self.object.name}: they have invoices on file. "
                "Invoices are kept for the audit trail and block client deletion."
            )
            return redirect('client_list')

class InvoiceListView(InvoiceOwnershipMixin, ListView):
    model = Invoice
    template_name = 'billing/invoice_list.html'
    context_object_name = 'invoices'

    def get_queryset(self):
        return super().get_queryset().select_related('client')

class InvoiceDetailView(InvoiceOwnershipMixin, DetailView):
    model = Invoice
    template_name = 'billing/invoice_detail.html'
    context_object_name = 'invoice'

    def get_queryset(self):
        return super().get_queryset().select_related('client').prefetch_related(
            Prefetch('items', queryset=LineItem.objects.order_by('pk'))
        )

class InvoiceCreateView(InvoiceOwnershipMixin, CreateView):
    model = Invoice
    form_class = InvoiceForm
    template_name = 'billing/invoice_form.html'
    success_url = reverse_lazy('invoice_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        if self.request.POST:
            data['formset'] = LineItemFormSet(self.request.POST)
        else:
            data['formset'] = LineItemFormSet()
        return data

    def form_valid(self, form):
        context = self.get_context_data()
        formset = context['formset']
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                self.object = form.save(commit=False)
                self.object.owner = self.request.user
                # Race-safe: see Invoice.next_number_for docstring for how
                # this avoids two concurrent creates computing the same number.
                self.object.number = Invoice.next_number_for(self.object.owner)
                # Freeze the client's currency onto the invoice at creation
                # time; see Invoice.currency for why this isn't read live.
                self.object.currency = self.object.client.currency
                self.object.save()
                formset.instance = self.object
                formset.save()
                # Trigger recalculate_total via save() after line items are saved
                self.object.save()
            return redirect(self.success_url)
        return self.render_to_response(self.get_context_data(form=form))

class InvoiceUpdateView(InvoiceOwnershipMixin, UpdateView):
    model = Invoice
    form_class = InvoiceForm
    template_name = 'billing/invoice_form.html'
    success_url = reverse_lazy('invoice_list')

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        invoice = get_object_or_404(Invoice.objects.filter(owner=request.user), pk=kwargs['pk'])
        if invoice.status != Invoice.Status.DRAFT:
            messages.error(
                request,
                'Only draft invoices can be edited. Issued (sent/paid) invoices are locked.'
            )
            return redirect('invoice_detail', pk=invoice.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        if self.request.POST:
            data['formset'] = LineItemFormSet(self.request.POST, instance=self.object)
        else:
            data['formset'] = LineItemFormSet(instance=self.object)
        return data

    def form_valid(self, form):
        context = self.get_context_data()
        formset = context['formset']
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                self.object = form.save()
                formset.instance = self.object
                formset.save()
                # Trigger recalculate_total via save() after line items are saved
                self.object.save()
            return redirect(self.success_url)
        return self.render_to_response(self.get_context_data(form=form))

class InvoiceDeleteView(InvoiceOwnershipMixin, DeleteView):
    model = Invoice
    template_name = 'billing/invoice_confirm_delete.html'
    success_url = reverse_lazy('invoice_list')

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        invoice = get_object_or_404(Invoice.objects.filter(owner=request.user), pk=kwargs['pk'])
        if invoice.status != Invoice.Status.DRAFT:
            messages.error(
                request,
                'Only draft invoices can be deleted. Issued invoices must remain for audit trail.'
            )
            return redirect('invoice_detail', pk=invoice.pk)
        return super().dispatch(request, *args, **kwargs)

class InvoiceStatusUpdateView(InvoiceOwnershipMixin, View):
    def post(self, request, pk, new_status):
        invoice = get_object_or_404(self.get_queryset(), pk=pk)
        
        # Enforce transitions. DRAFT->SENT is not handled here: it only
        # happens through InvoiceSendView, which generates the PDF, emails
        # the client, and freezes the total.
        if invoice.status == Invoice.Status.SENT and new_status == 'paid':
            invoice.status = Invoice.Status.PAID
        else:
            return HttpResponseBadRequest(f"Invalid transition from {invoice.status} to {new_status}")
            
        invoice.save()
        return redirect('invoice_detail', pk=invoice.pk)

class InvoiceSendView(InvoiceOwnershipMixin, View):
    def post(self, request, pk):
        invoice = get_object_or_404(self.get_queryset(), pk=pk)
        try:
            send_invoice(invoice)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('invoice_detail', pk=invoice.pk)

        messages.success(request, f"Invoice sent to {invoice.client.email}.")
        return redirect('invoice_detail', pk=invoice.pk)

class InvoicePdfPreviewView(InvoiceOwnershipMixin, View):
    def get(self, request, pk):
        invoice = get_object_or_404(self.get_queryset(), pk=pk)
        pdf_bytes = render_invoice_pdf(invoice)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{invoice.number}.pdf"'
        return response

class CurrencyConverterView(LoginRequiredMixin, View):
    """Freelancer-only draft-time calculator. Deliberately not wired to any
    invoice: it only ever calls billing.fx, never touches Invoice/Payment."""
    template_name = 'billing/currency_converter.html'

    def get(self, request):
        return render(request, self.template_name, {'currencies': Currency.choices})

    def post(self, request):
        amount_raw = request.POST.get('amount', '').strip()
        base = request.POST.get('base', '')
        target = request.POST.get('target', '')
        context = {
            'currencies': Currency.choices,
            'amount': amount_raw,
            'base': base,
            'target': target,
        }

        try:
            amount = Decimal(amount_raw)
        except InvalidOperation:
            context['error'] = "Enter a valid amount."
            return render(request, self.template_name, context)

        try:
            context['conversion'] = fx.convert(amount, base, target)
        except ValueError as e:
            context['error'] = str(e)

        return render(request, self.template_name, context)

# Public, unauthenticated views: reached by a client via the invoice's
# unguessable token, not by owner login.

class PublicInvoiceDetailView(DetailView):
    model = Invoice
    template_name = 'billing/public_invoice.html'
    context_object_name = 'invoice'
    slug_field = 'token'
    slug_url_kwarg = 'token'

    def get_queryset(self):
        return Invoice.objects.select_related('client', 'owner').prefetch_related(
            Prefetch('items', queryset=LineItem.objects.order_by('pk'))
        )

class PublicInvoiceCheckoutView(View):
    def post(self, request, token):
        invoice = get_object_or_404(
            Invoice.objects.select_related('client'), token=token
        )
        try:
            authorization_url = initialize_payment(invoice, request)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('public_invoice', token=token)

        return redirect(authorization_url)

@csrf_exempt
@require_POST
def paystack_webhook(request):
    """Server-side source of truth for payments: only this view ever marks
    an invoice PAID or creates a Payment row. The browser callback
    (PublicInvoiceDetailView, reached via initialize_payment's callback_url)
    is UX only — a client landing there proves nothing about whether the
    charge actually succeeded."""
    secret = settings.PAYSTACK_SECRET_KEY
    if not secret:
        # Server misconfiguration, not a failed caller auth — 503 (not 401)
        # so Paystack's retry survives once the key is actually set, and so
        # we never reach secret.encode() on None below.
        logger.error("Paystack webhook called but PAYSTACK_SECRET_KEY is not configured")
        return HttpResponse(status=503)

    payload = request.body  # raw bytes — the signature is computed over exactly this
    computed = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
    sig = request.headers.get('x-paystack-signature', '')
    if not hmac.compare_digest(computed, sig):
        return HttpResponse(status=401)

    event = json.loads(payload)
    if event.get('event') != 'charge.success':
        return HttpResponse(status=200)

    data = event['data']
    reference = data['reference']
    amount_subunit = data['amount']
    currency = data['currency']
    channel = data.get('channel', '')
    invoice_token = data.get('metadata', {}).get('invoice_token')

    invoice = Invoice.objects.filter(token=invoice_token).first()
    if invoice is None:
        return HttpResponse(status=200)

    expected = int((invoice.total * Decimal("100")).to_integral_value())
    if amount_subunit != expected or currency != invoice.currency:
        logger.warning(
            "Paystack webhook amount/currency mismatch for invoice %s: "
            "expected %s %s, got %s %s (reference=%s)",
            invoice.pk, expected, invoice.currency, amount_subunit, currency, reference,
        )
        return HttpResponse(status=200)

    with transaction.atomic():
        payment, created = Payment.objects.get_or_create(
            reference=reference,
            defaults=dict(
                invoice=invoice,
                amount=(Decimal(amount_subunit) / 100),
                channel=channel,
                status='success',
                raw_payload=event,
            ),
        )
        if created and invoice.status == Invoice.Status.SENT:
            invoice.status = Invoice.Status.PAID
            invoice.save(update_fields=['status'])

    return HttpResponse(status=200)
