from django.contrib import admin
from .models import Client, Invoice, LineItem

class LineItemInline(admin.TabularInline):
    model = LineItem
    extra = 1

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'email', 'company')
    list_filter = ('owner',)

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('number', 'owner', 'client', 'status', 'issue_date', 'total')
    list_filter = ('status', 'owner')
    inlines = [LineItemInline]

@admin.register(LineItem)
class LineItemAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'description', 'quantity', 'unit_price')
