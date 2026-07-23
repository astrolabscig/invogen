from django.urls import path
from . import views

urlpatterns = [
    path('', views.InvoiceListView.as_view(), name='invoice_list'),
    path('<int:pk>/', views.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('new/', views.InvoiceCreateView.as_view(), name='invoice_create'),
    path('<int:pk>/edit/', views.InvoiceUpdateView.as_view(), name='invoice_update'),
    path('<int:pk>/delete/', views.InvoiceDeleteView.as_view(), name='invoice_delete'),
    path('<int:pk>/status/<str:new_status>/', views.InvoiceStatusUpdateView.as_view(), name='invoice_status_update'),
]
