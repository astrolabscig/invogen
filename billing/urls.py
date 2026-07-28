from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    
    # Auth URLs
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    # Django 5.0+ LogoutView requires POST, so we can use a custom template or handle it. Let's use LogoutView.
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.RegisterView.as_view(), name='register'),
    
    # Client URLs
    path('clients/', views.ClientListView.as_view(), name='client_list'),
    path('clients/new/', views.ClientCreateView.as_view(), name='client_create'),
    path('clients/<int:pk>/edit/', views.ClientUpdateView.as_view(), name='client_update'),
    path('clients/<int:pk>/delete/', views.ClientDeleteView.as_view(), name='client_delete'),
    
    # Invoice URLs
    path('invoices/', views.InvoiceListView.as_view(), name='invoice_list'),
    path('invoices/<int:pk>/', views.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoices/new/', views.InvoiceCreateView.as_view(), name='invoice_create'),
    path('invoices/<int:pk>/edit/', views.InvoiceUpdateView.as_view(), name='invoice_update'),
    path('invoices/<int:pk>/delete/', views.InvoiceDeleteView.as_view(), name='invoice_delete'),
    path('invoices/<int:pk>/status/<str:new_status>/', views.InvoiceStatusUpdateView.as_view(), name='invoice_status_update'),
    path('invoices/<int:pk>/send/', views.InvoiceSendView.as_view(), name='invoice_send'),
    path('invoices/<int:pk>/pdf-preview/', views.InvoicePdfPreviewView.as_view(), name='invoice_pdf_preview'),

    # Tools
    path('tools/converter/', views.CurrencyConverterView.as_view(), name='currency_converter'),

    # Public (unauthenticated) invoice URLs
    path('pay/<uuid:token>/', views.PublicInvoiceDetailView.as_view(), name='public_invoice'),
    path('pay/<uuid:token>/checkout/', views.PublicInvoiceCheckoutView.as_view(), name='public_invoice_checkout'),

    # Webhooks
    path('webhooks/paystack/', views.paystack_webhook, name='paystack_webhook'),
]
