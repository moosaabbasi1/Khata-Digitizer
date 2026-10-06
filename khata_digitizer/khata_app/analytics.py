"""
Dashboard analytics for Phase 6.

Kept in its own module rather than views.py so the actual math is easy to
unit-test in isolation from HTTP request handling.
"""

from dataclasses import dataclass
from decimal import Decimal


def _to_decimal(value) -> Decimal:
    """Safely turn a float/int/Decimal/None into a Decimal via its string
    representation — going through str() avoids the binary floating-point
    artifacts you'd get converting a float to Decimal directly."""
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


@dataclass
class DashboardTotals:
    total_sales: Decimal
    total_credit_pending: Decimal
    total_paid: Decimal
    profit_total: Decimal
    items_total_count: int
    items_with_cost_count: int

    @property
    def profit_is_partial(self) -> bool:
        """True if profit is based on only some of the items — i.e. the
        number is real but incomplete, not a full picture."""
        return 0 < self.items_with_cost_count < self.items_total_count

    @property
    def profit_has_no_data(self) -> bool:
        return self.items_total_count > 0 and self.items_with_cost_count == 0


def compute_dashboard_totals(items_queryset) -> DashboardTotals:
    """
    Aggregate a ChitItem queryset into the dashboard's headline numbers.

    Done in Python rather than as a database-level aggregate on purpose:
    `price`/`cost_price` are DecimalField but `quantity` is a FloatField,
    and multiplying a Decimal field by a Float field inside a Django ORM
    F() expression is fragile — behavior differs across database backends
    (SQLite is forgiving, MSSQL is stricter about implicit type
    conversions). A single shopkeeper's chit volume is small enough that
    plain Python summation is both simpler and more portable than fighting
    that at the SQL level.
    """
    total_sales = Decimal("0")
    total_credit_pending = Decimal("0")
    profit_total = Decimal("0")
    items_total_count = 0
    items_with_cost_count = 0

    for row in items_queryset.values("price", "quantity", "is_credit", "is_paid", "cost_price"):
        items_total_count += 1
        qty = _to_decimal(row["quantity"])
        price = _to_decimal(row["price"])
        line_total = price * qty
        total_sales += line_total

        # Only count credit as pending if it has not yet been paid/settled
        if row["is_credit"] and not row.get("is_paid", False):
            total_credit_pending += line_total

        if row["cost_price"] is not None:
            items_with_cost_count += 1
            cost = _to_decimal(row["cost_price"])
            profit_total += (price - cost) * qty

    return DashboardTotals(
        total_sales=total_sales,
        total_credit_pending=total_credit_pending,
        total_paid=total_sales - total_credit_pending,
        profit_total=profit_total,
        items_total_count=items_total_count,
        items_with_cost_count=items_with_cost_count,
    )
