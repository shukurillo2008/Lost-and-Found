"""One-shot backfill: fill trilingual description streams for existing reports.

For every lost/found report the canonical ``description`` is copied into
the reporter-language stream (deterministic, no network) and the other two
blank streams are translated online through the shared translator.
Already filled streams are never overwritten, so the command is idempotent
and safe to re-run (send throttles are simply retried by running again).
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from catalog.translation import auto_fill
from reports.models import FoundReport, LostReport

REPORT_MODELS = (LostReport, FoundReport)


class Command(BaseCommand):
    help = "Backfill description_uz/_en/_ru language streams for existing reports."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be filled without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        # The command is explicitly requested: force translation on even when
        # AUTO_TRANSLATE is off for routine saves.
        restore = getattr(settings, "AUTO_TRANSLATE", False)
        settings.AUTO_TRANSLATE = True
        try:
            filled = 0
            for model in REPORT_MODELS:
                label = model.__name__
                for report in (
                    model.objects.exclude(description="")
                    .select_related("reporter")
                    .iterator()
                ):
                    src = (report.reporter.language if report.reporter_id else "en") or "en"
                    if src not in ("uz", "ru", "en"):
                        src = "en"
                    fields_map = {
                        lang: (getattr(report, f"description_{lang}", "") or "")
                        for lang in ("uz", "en", "ru")
                    }
                    fields_map[src] = report.description
                    auto_fill(fields_map, source_lang=src)
                    updates = {
                        f"description_{lang}": value
                        for lang, value in fields_map.items()
                        if value != (getattr(report, f"description_{lang}", "") or "")
                    }
                    if not updates:
                        continue
                    filled += 1
                    if dry_run:
                        self.stdout.write(
                            f"{label} #{report.pk}: would fill "
                            + ", ".join(sorted(updates))
                        )
                        continue
                    model.objects.filter(pk=report.pk).update(**updates)
                    self.stdout.write(f"{label} #{report.pk}: filled")
        finally:
            settings.AUTO_TRANSLATE = restore
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Would backfill' if dry_run else 'Backfilled'} {filled} report(s)."
            )
        )
