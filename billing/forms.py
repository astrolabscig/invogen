from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from .models import Invoice, LineItem, Client


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['name', 'email', 'company', 'address']

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if self.user:
            existing = Client.objects.filter(owner=self.user, email=email)
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise forms.ValidationError("You already have a client with this email.")
        return email


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        # 'number' is intentionally excluded: it's auto-assigned per-owner
        # sequentially (see Invoice.next_number_for), never user-entered.
        fields = ['client', 'issue_date', 'due_date', 'notes']
        widgets = {
            'issue_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields['client'].queryset = Client.objects.filter(owner=user)


class LineItemForm(forms.ModelForm):
    class Meta:
        model = LineItem
        fields = ['description', 'quantity', 'unit_price']


class BaseLineItemFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return

        valid_items = 0
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue
            if not form.cleaned_data:
                continue
            if form.cleaned_data.get('description') or form.cleaned_data.get('quantity') is not None:
                valid_items += 1

        if valid_items == 0:
            raise forms.ValidationError('Add at least one line item before saving the invoice.')


LineItemFormSet = inlineformset_factory(
    Invoice,
    LineItem,
    form=LineItemForm,
    formset=BaseLineItemFormSet,
    extra=3,
    can_delete=True,
)
