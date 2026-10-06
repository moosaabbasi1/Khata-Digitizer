import json

from django.core.management.base import BaseCommand, CommandError

from khata_app.services import extract_text, parse_chit_text, preprocess_image


class Command(BaseCommand):
    help = (
        "Phase 4 verification: run a chit image through the OCR pipeline "
        "and print the extracted text + parsed items to the terminal. "
        "Usage: python manage.py test_ocr path/to/chit.jpg"
    )

    def add_arguments(self, parser):
        parser.add_argument("image_path", type=str)

    def handle(self, *args, **options):
        path = options["image_path"]
        try:
            with open(path, "rb") as f:
                image_bytes = f.read()
        except OSError as exc:
            raise CommandError(f"Could not read '{path}': {exc}")

        preprocessed = preprocess_image(image_bytes)
        raw_text = extract_text(preprocessed)
        parsed = parse_chit_text(raw_text)

        self.stdout.write(self.style.MIGRATE_HEADING("Raw OCR text:"))
        self.stdout.write(raw_text or "(nothing extracted)")

        self.stdout.write(self.style.MIGRATE_HEADING("\nParsed items:"))
        items_json = [
            {"item_name": i.item_name, "price": i.price, "quantity": i.quantity}
            for i in parsed.items
        ]
        self.stdout.write(json.dumps(items_json, indent=2, ensure_ascii=False))

        if parsed.unparsed_lines:
            self.stdout.write(self.style.WARNING("\nLines that didn't parse (will need manual review):"))
            for line in parsed.unparsed_lines:
                self.stdout.write(f"  - {line!r}")
