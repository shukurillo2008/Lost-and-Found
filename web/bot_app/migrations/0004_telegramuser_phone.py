from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bot_app", "0003_digestrun_attempts_digestrun_last_attempt_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="telegramuser",
            name="phone",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
    ]
