from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("matching", "0002_matchsuggestion_match_status_score_idx"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="matchsuggestion",
            constraint=models.UniqueConstraint(
                fields=("lost_report",),
                condition=Q(status="confirmed"),
                name="unique_confirmed_suggestion_per_report",
            ),
        ),
    ]
