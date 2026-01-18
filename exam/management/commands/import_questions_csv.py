import csv
from django.core.management.base import BaseCommand
from django.db import transaction
from exam.models import Package, Section, Question, Choice


class Command(BaseCommand):
    help = "Import questions from CSV"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str)

    @transaction.atomic
    def handle(self, *args, **options):
        path = options["csv_path"]

        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            current_question = None
            last_key = None

            for i, row in enumerate(reader, start=2):
                try:
                    package = Package.objects.get(slug=row["package_slug"])
                except Package.DoesNotExist:
                    self.stderr.write(f"[Line {i}] Package not found: {row['package_slug']}")
                    continue

                section = None
                if row.get("section_title"):
                    section, _ = Section.objects.get_or_create(
                        title=row["section_title"],
                        package=package,
                        defaults={"order_index": 0},
                    )

                key = (
                    row["package_slug"],
                    row.get("section_title"),
                    row["stem"],
                )

                if key != last_key:
                    current_question = Question.objects.create(
                        package=package,
                        section=section,
                        stem=row["stem"],
                        explanation=row.get("explanation", ""),
                        answer_type=row["answer_type"],
                        order_index=int(row.get("order_index") or 0),
                        is_active=True,
                    )
                    last_key = key

                Choice.objects.create(
                    question=current_question,
                    label=row["choice_label"],
                    text=row["choice_text"],
                    points=int(row.get("choice_points") or 0),
                    is_correct=str(row.get("is_correct", "0")) == "1",
                )

            self.stdout.write(self.style.SUCCESS("Import selesai!"))
