from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, View, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.http import HttpResponseBadRequest
from django.contrib.auth.forms import UserCreationForm

class RegisterView(CreateView):
    form_class = UserCreationForm
    template_name = 'registration/register.html'
    success_url = reverse_lazy('login')


from .models import Invoice, LineItem, Client
from .forms import InvoiceForm, LineItemFormSet

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
    template_name = 'billing/client_form.html'
    fields = ['name', 'email', 'company', 'address']
    success_url = reverse_lazy('client_list')

    def form_valid(self, form):
        form.instance.owner = self.request.user
        return super().form_valid(form)

class ClientUpdateView(ClientOwnershipMixin, UpdateView):
    model = Client
    template_name = 'billing/client_form.html'
    fields = ['name', 'email', 'company', 'address']
    success_url = reverse_lazy('client_list')

class ClientDeleteView(ClientOwnershipMixin, DeleteView):
    model = Client
    template_name = 'billing/client_confirm_delete.html'
    success_url = reverse_lazy('client_list')

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

class InvoiceStatusUpdateView(InvoiceOwnershipMixin, View):
    def post(self, request, pk, new_status):
        invoice = get_object_or_404(self.get_queryset(), pk=pk)
        
        # Enforce transitions
        if invoice.status == Invoice.Status.DRAFT and new_status == 'sent':
            invoice.status = Invoice.Status.SENT
        elif invoice.status == Invoice.Status.SENT and new_status == 'paid':
            invoice.status = Invoice.Status.PAID
        else:
            return HttpResponseBadRequest(f"Invalid transition from {invoice.status} to {new_status}")
            
        invoice.save()
        return redirect('invoice_detail', pk=invoice.pk)
