# Generated by Django 1.11.3 on 2017-07-15 21:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("schedule", "0004_auto_20170715_0655"),
    ]

    operations = [
        migrations.AddField(
            model_name="schedule",
            name="published",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
