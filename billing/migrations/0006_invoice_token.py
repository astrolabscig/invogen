import uuid

from django.db import migrations, models


def backfill_invoice_tokens(apps, schema_editor):
    Invoice = apps.get_model('billing', 'Invoice')
    for invoice in Invoice.objects.all():
        invoice.token = uuid.uuid4()
        invoice.save(update_fields=['token'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0005_client_currency_invoice_currency'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='token',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(backfill_invoice_tokens, noop_reverse),
        migrations.AlterField(
            model_name='invoice',
            name='token',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
