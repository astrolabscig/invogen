from django.contrib import admin
from .models import Client, Invoice, LineItem, Payment

class LineItemInline(admin.TabularInline):
    model = LineItem
    extra = 1

class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ('reference', 'amount', 'channel', 'status', 'raw_payload', 'created_at')
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'email', 'company')
    list_filter = ('owner',)

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('number', 'owner', 'client', 'status', 'issue_date', 'total')
    list_filter = ('status', 'owner')
    inlines = [LineItemInline, PaymentInline]

@admin.register(LineItem)
class LineItemAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'description', 'quantity', 'unit_price')
