from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from .models import Invoice, LineItem, Client


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['client', 'number', 'issue_date', 'due_date', 'notes']
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
