import os
import random
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from billing.models import Client, Invoice, LineItem

class Command(BaseCommand):
    help = 'Seeds the database with a demo user, clients, and invoices.'

    def handle(self, *args, **kwargs):
        if User.objects.filter(username='demo').exists():
            self.stdout.write(self.style.WARNING("Demo user already exists. Aborting seed."))
            return

        # Create demo user
        user = User.objects.create_user(username='demo', password='demo12345')
        self.stdout.write(self.style.SUCCESS("Created demo user (demo / demo12345)."))

        # Create 3 clients
        clients = [
            Client.objects.create(owner=user, name="Acme Corp", email="contact@acme.com", company="Acme Corp"),
            Client.objects.create(owner=user, name="Globex", email="info@globex.com", company="Globex Inc"),
            Client.objects.create(owner=user, name="Initech", email="billing@initech.com", company="Initech LLC"),
        ]
        self.stdout.write(self.style.SUCCESS("Created 3 clients."))

        # Create 5 invoices (spread across DRAFT, SENT, PAID)
        statuses = [
            Invoice.Status.DRAFT,
            Invoice.Status.SENT,
            Invoice.Status.PAID,
            Invoice.Status.SENT,
            Invoice.Status.PAID
        ]

        descriptions = ["Consulting hours", "Web development", "Server maintenance", "SEO optimization"]

        for i in range(5):
            invoice = Invoice(
                owner=user,
                client=random.choice(clients),
                number=f"INV-{1000 + i}",
                status=statuses[i],
                issue_date=date.today() - timedelta(days=random.randint(1, 30)),
                due_date=date.today() + timedelta(days=random.randint(1, 30)),
            )
            # Save initially as draft to allow total calculation
            invoice.status = Invoice.Status.DRAFT
            invoice.save()

            # Add 2-4 line items
            for _ in range(random.randint(2, 4)):
                LineItem.objects.create(
                    invoice=invoice,
                    description=random.choice(descriptions),
                    quantity=round(random.uniform(1.0, 10.0), 2),
                    unit_price=round(random.uniform(50.0, 150.0), 2)
                )
            
            # Save again to calculate total
            invoice.save()
            
            # Now update to actual target status
            invoice.status = statuses[i]
            # Bypass custom save to avoid recalculating total if not draft, though custom save handles this.
            # We call save() again which will skip recalculate_total if status != DRAFT.
            invoice.save()

        self.stdout.write(self.style.SUCCESS("Created 5 invoices with line items."))
        self.stdout.write(self.style.SUCCESS("Seed complete!"))
