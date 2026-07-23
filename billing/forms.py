from django import forms
from django.forms import inlineformset_factory
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

LineItemFormSet = inlineformset_factory(
    Invoice,
    LineItem,
    form=LineItemForm,
    extra=3,
    can_delete=True
)
