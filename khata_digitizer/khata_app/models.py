import uuid
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model for shopkeepers.

    Uses a UUID primary key instead of Django's default auto-incrementing
    integer ID — this is required project-wide so that no URL ever leaks a
    guessable sequential ID (see Phase 3+ models, which all follow the same
    pattern).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Extra shopkeeper profile fields. Everything from AbstractUser
    # (username, email, password, first_name, last_name, etc.) is inherited.
    shop_name = models.CharField(max_length=255, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    shop_address = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.shop_name or self.username


class Customer(models.Model):
    """
    A shopkeeper's customer — the person a Khata (credit) chit is tracked
    against. Not a login-capable account, just a record the shopkeeper
    keeps.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shopkeeper = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="customers"
    )
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Seller(models.Model):
    """
    A seller/wholesaler/supplier from whom the shopkeeper bought products or inventory.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shopkeeper = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="sellers"
    )
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


CHIT_TYPE_CHOICES = (
    ("customer", "Customer (Sale / Udhar)"),
    ("seller", "Seller / Supplier (Purchase)"),
)


class KhataChit(models.Model):
    """
    One uploaded photo of a handwritten Khata chit, and the shopkeeper it
    belongs to. Can be associated with either a customer (sales/udhar) or
    a seller/wholesaler (inventory purchase).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shopkeeper = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="khata_chits"
    )
    chit_type = models.CharField(
        max_length=20,
        choices=CHIT_TYPE_CHOICES,
        default="customer",
        db_index=True,
        help_text="Whether this chit is from a customer sale or a seller purchase.",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        related_name="khata_chits",
        null=True,
        blank=True,
        db_index=True,
    )
    seller = models.ForeignKey(
        Seller,
        on_delete=models.SET_NULL,
        related_name="khata_chits",
        null=True,
        blank=True,
        db_index=True,
    )
    image = models.ImageField(upload_to="khata_chits/%Y/%m/")
    upload_date = models.DateTimeField(auto_now_add=True, db_index=True)

    # Phase 4/5: the OCR pipeline's raw output, cached here so the review
    # page (Phase 5) only has to re-run the cheap text parser on repeat
    # visits, not the expensive image-preprocessing + Tesseract call.
    ocr_raw_text = models.TextField(
        blank=True,
        help_text="Raw text extracted by the OCR pipeline, before human review.",
    )
    ocr_processed_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the OCR pipeline last ran on this chit's image.",
    )

    class Meta:
        ordering = ["-upload_date"]
        indexes = [
            models.Index(fields=["shopkeeper", "upload_date"]),
            models.Index(fields=["shopkeeper", "chit_type"]),
        ]

    @property
    def party_type_label(self) -> str:
        return "Seller / Supplier" if self.chit_type == "seller" else "Customer"

    @property
    def party_name(self) -> str:
        if self.chit_type == "seller":
            return self.seller.name if self.seller else "Unspecified Seller"
        return self.customer.name if self.customer else "Unassigned Customer"

    @property
    def party_phone(self) -> str:
        if self.chit_type == "seller":
            return self.seller.phone if self.seller else ""
        return self.customer.phone if self.customer else ""

    @property
    def total_amount(self) -> Decimal:
        """Calculates total without N+1 queries by leveraging prefetched items."""
        return sum((item.line_total for item in self.items.all()), Decimal("0"))

    @property
    def pending_credit_amount(self) -> Decimal:
        """Calculates pending credit without N+1 queries by leveraging prefetched items."""
        return sum(
            (item.line_total for item in self.items.all() if item.is_credit and not item.is_paid),
            Decimal("0"),
        )

    def __str__(self):
        return f"Chit [{self.get_chit_type_display()}] ({self.party_name}) — {self.upload_date:%Y-%m-%d}"


class ChitItem(models.Model):
    """
    A single line item extracted (via OCR, Phase 4+) from a KhataChit —
    one row per item/price the OCR pipeline pulls off the handwritten chit,
    after the shopkeeper has reviewed and corrected it (Phase 5).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chit = models.ForeignKey(
        KhataChit, on_delete=models.CASCADE, related_name="items", db_index=True
    )
    item_name = models.CharField(max_length=255)
    quantity = models.FloatField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_credit = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Checked if this item was given on credit rather than paid for immediately.",
    )
    is_paid = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Only meaningful when is_credit is True. Marks a credit entry as settled.",
    )
    paid_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When the customer settled this credit item.",
    )
    # Phase 6: the roadmap asks the dashboard to show "estimated profit", but
    # nothing in the original schema captures what the shopkeeper paid for
    # an item — without that, "profit" would just be total sales relabeled,
    # which would mislead a shopkeeper about their actual margins. This is
    # optional and blank by default: profit is only ever calculated from
    # items where a cost was actually entered, and the dashboard says so
    # explicitly rather than presenting a number that looks complete but
    # isn't.
    cost_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="What you paid for this item (optional) — used to estimate profit. Leave blank if you don't track this.",
    )

    class Meta:
        indexes = [
            models.Index(fields=["chit", "is_credit", "is_paid"]),
            models.Index(fields=["is_credit", "is_paid"]),
        ]

    @property
    def line_total(self) -> Decimal:
        return Decimal(str(self.price)) * Decimal(str(self.quantity))

    def __str__(self):
        return f"{self.item_name} x{self.quantity}"
