from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .analytics import compute_dashboard_totals
from .forms import (
    ChitItemEditFormSet,
    ChitItemForm,
    ChitItemFormSet,
    ChitPartyUpdateForm,
    ChitUploadForm,
    ShopkeeperRegistrationForm,
)
from .models import ChitItem, Customer, KhataChit, Seller
from .services import process_chit_image


def invalidate_shopkeeper_cache(user_id):
    """Evict cached financial aggregations for this shopkeeper."""
    for p in ["today", "week", "month", "all"]:
        cache.delete(f"dash_totals_{user_id}_{p}")


def register(request):
    """
    Shopkeeper self-registration.
    Logs the user in immediately on success so they land straight on their
    dashboard instead of having to log in a second time.
    """
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = ShopkeeperRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("dashboard")
    else:
        form = ShopkeeperRegistrationForm()

    return render(request, "khata_app/register.html", {"form": form})


def user_logout(request):
    """
    Safely logs out the user on both GET and POST requests, then redirects to login.
    Django 5.0's built-in LogoutView rejects GET requests with HTTP 405 Method Not Allowed.
    This view supports both methods so users never encounter a 405 error when logging out.
    """
    auth_logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect("login")


@login_required
def dashboard(request):
    """
    High-performance analytics dashboard with in-memory caching,
    period filters, prefetched relations, and pending credit summary.
    """
    period = request.GET.get("period", "today")
    if period not in {"today", "week", "month", "all"}:
        period = "today"

    now_local = timezone.localtime(timezone.now())
    if period == "today":
        start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = (now_local - timedelta(days=now_local.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "month":
        start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = None

    chits_qs = KhataChit.objects.filter(shopkeeper=request.user)
    if start is not None:
        chits_qs = chits_qs.filter(upload_date__gte=start)

    # Server-side cache for high-frequency dashboard queries
    cache_key = f"dash_totals_{request.user.id}_{period}"
    totals = cache.get(cache_key)
    if totals is None:
        items_qs = ChitItem.objects.filter(chit__in=chits_qs)
        totals = compute_dashboard_totals(items_qs)
        cache.set(cache_key, totals, 60)

    # Optimized recent chits query with prefetched relations (0 N+1 queries)
    recent_chits = (
        chits_qs.select_related("customer", "seller")
        .prefetch_related("items")
        .annotate(items_count=Count("items"))
        .order_by("-upload_date")[:10]
    )

    # Active pending credit items for this shopkeeper (Udhar list)
    pending_credit_items_qs = (
        ChitItem.objects.filter(
            chit__shopkeeper=request.user,
            is_credit=True,
            is_paid=False,
        )
        .select_related("chit", "chit__customer", "chit__seller")
        .order_by("-chit__upload_date")
    )
    total_pending_count = pending_credit_items_qs.count()
    pending_credit_items = pending_credit_items_qs[:10]

    return render(
        request,
        "khata_app/dashboard.html",
        {
            "user": request.user,
            "recent_chits": recent_chits,
            "pending_credit_items": pending_credit_items,
            "total_pending_count": total_pending_count,
            "period": period,
            "periods": [
                ("today", "Today"),
                ("week", "This week"),
                ("month", "This month"),
                ("all", "All time"),
            ],
            "totals": totals,
        },
    )


@login_required
def chit_upload(request):
    """
    Step 1 of Phase 5: shopkeeper uploads a photo of a chit.
    Runs OCR on upload and renders the review screen for human-in-the-loop verification.
    """
    if request.method == "POST":
        form = ChitUploadForm(request.POST, request.FILES, shopkeeper=request.user)
        if form.is_valid():
            chit = form.save(commit=True)

            chit.image.open("rb")
            try:
                parsed = process_chit_image(chit.image.read())
            finally:
                chit.image.close()

            chit.ocr_raw_text = parsed.raw_text
            chit.ocr_processed_at = timezone.now()
            chit.save(update_fields=["ocr_raw_text", "ocr_processed_at"])

            initial_rows = [
                {
                    "item_name": item.item_name,
                    "quantity": item.quantity,
                    "price": item.price,
                }
                for item in parsed.items
            ]

            UploadReviewFormSet = modelformset_factory(
                ChitItem, form=ChitItemForm, extra=len(initial_rows) + 3, can_delete=True
            )
            formset = UploadReviewFormSet(
                queryset=ChitItem.objects.none(), initial=initial_rows
            )
            return render(
                request,
                "khata_app/review_chit.html",
                {
                    "chit": chit,
                    "formset": formset,
                    "raw_text": parsed.raw_text,
                    "unparsed_lines": parsed.unparsed_lines,
                },
            )
    else:
        form = ChitUploadForm(shopkeeper=request.user)

    return render(request, "khata_app/upload_chit.html", {"form": form})


@login_required
def chit_review(request, chit_id):
    """
    Step 2 of Phase 5: the shopkeeper submits their reviewed/corrected
    items, and only now do they get saved as ChitItem rows.
    """
    chit = get_object_or_404(KhataChit, id=chit_id, shopkeeper=request.user)

    if request.method != "POST":
        return redirect("chit_upload")

    formset = ChitItemFormSet(request.POST, queryset=ChitItem.objects.none())
    if formset.is_valid():
        items = formset.save(commit=False)
        for item in items:
            item.chit = chit
            item.save()
        invalidate_shopkeeper_cache(request.user.id)
        messages.success(
            request, f"Saved {len(items)} item(s) to this chit."
        )
        return redirect("chit_detail", chit_id=chit.id)

    return render(
        request,
        "khata_app/review_chit.html",
        {"chit": chit, "formset": formset, "raw_text": "", "unparsed_lines": []},
    )


@login_required
def chit_detail(request, chit_id):
    """
    Displays complete details for a single chit: photo, linked customer/seller,
    and all purchased items with credit and payment statuses.
    """
    chit = get_object_or_404(
        KhataChit.objects.select_related("customer", "seller").prefetch_related("items"),
        id=chit_id,
        shopkeeper=request.user,
    )

    items = chit.items.all()
    total_amount = sum((item.line_total for item in items), Decimal("0"))
    credit_pending = sum(
        (item.line_total for item in items if item.is_credit and not item.is_paid),
        Decimal("0"),
    )
    credit_settled = sum(
        (item.line_total for item in items if item.is_credit and item.is_paid),
        Decimal("0"),
    )
    cash_amount = sum(
        (item.line_total for item in items if not item.is_credit),
        Decimal("0"),
    )

    return render(
        request,
        "khata_app/chit_detail.html",
        {
            "chit": chit,
            "items": items,
            "total_amount": total_amount,
            "credit_pending": credit_pending,
            "credit_settled": credit_settled,
            "cash_amount": cash_amount,
        },
    )


@login_required
def chit_edit(request, chit_id):
    """
    Allows a shopkeeper to edit existing line items of a chit
    as well as party information (Customer vs Seller).
    """
    chit = get_object_or_404(KhataChit, id=chit_id, shopkeeper=request.user)

    if request.method == "POST":
        party_form = ChitPartyUpdateForm(request.POST, instance=chit, shopkeeper=request.user)
        formset = ChitItemEditFormSet(request.POST, queryset=chit.items.all())
        if party_form.is_valid() and formset.is_valid():
            party_form.save()
            instances = formset.save(commit=False)
            for instance in instances:
                instance.chit = chit
                if instance.is_credit and instance.is_paid and not instance.paid_at:
                    instance.paid_at = timezone.now()
                elif not instance.is_paid:
                    instance.paid_at = None
                instance.save()

            for deleted_object in formset.deleted_objects:
                deleted_object.delete()

            invalidate_shopkeeper_cache(request.user.id)
            messages.success(request, "Chit details and items updated successfully.")
            return redirect("chit_detail", chit_id=chit.id)
    else:
        party_form = ChitPartyUpdateForm(instance=chit, shopkeeper=request.user)
        formset = ChitItemEditFormSet(queryset=chit.items.all())

    return render(
        request,
        "khata_app/chit_edit.html",
        {
            "chit": chit,
            "party_form": party_form,
            "formset": formset,
        },
    )


@login_required
@require_POST
def item_toggle_paid(request, item_id):
    """
    One-click action to mark a credit item as paid/settled, or revert it to pending.
    Tenant-scoped: verifies the item belongs to a chit owned by request.user.
    """
    item = get_object_or_404(
        ChitItem.objects.select_related("chit"),
        id=item_id,
        chit__shopkeeper=request.user,
    )

    if not item.is_credit:
        messages.warning(request, f"'{item.item_name}' was not recorded as a credit purchase.")
        return redirect("dashboard")

    # Toggle payment status
    if item.is_paid:
        item.is_paid = False
        item.paid_at = None
        item.save(update_fields=["is_paid", "paid_at"])
        invalidate_shopkeeper_cache(request.user.id)
        messages.info(
            request,
            f"Marked '{item.item_name}' (Rs {item.line_total:.2f}) as UNPAID (Credit Pending).",
        )
    else:
        item.is_paid = True
        item.paid_at = timezone.now()
        item.save(update_fields=["is_paid", "paid_at"])
        invalidate_shopkeeper_cache(request.user.id)
        messages.success(
            request,
            f"Payment received! Marked '{item.item_name}' (Rs {item.line_total:.2f}) as PAID.",
        )

    # Return to previous page or chit detail or dashboard
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url:
        return redirect(next_url)
    return redirect("chit_detail", chit_id=item.chit.id)


@login_required
def credit_list(request):
    """
    Credit Khata / Udhar Ledger.
    Displays all items bought on credit with customer name, phone, product,
    quantity, price, total amount, status (Pending vs Paid), pagination, and actions.
    """
    status_filter = request.GET.get("status", "pending")
    customer_id = request.GET.get("customer")
    page_number = request.GET.get("page", 1)

    credit_items_qs = (
        ChitItem.objects.filter(
            chit__shopkeeper=request.user,
            is_credit=True,
        )
        .select_related("chit", "chit__customer", "chit__seller")
        .order_by("-chit__upload_date")
    )

    if customer_id:
        credit_items_qs = credit_items_qs.filter(chit__customer_id=customer_id)

    # Fast lightweight statistical aggregation
    raw_stats = credit_items_qs.values("price", "quantity", "is_paid")
    total_credit_amount = Decimal("0")
    pending_credit_amount = Decimal("0")
    settled_credit_amount = Decimal("0")
    pending_count = 0

    for row in raw_stats:
        qty = Decimal(str(row["quantity"]))
        price = Decimal(str(row["price"]))
        line_val = price * qty
        total_credit_amount += line_val
        if row["is_paid"]:
            settled_credit_amount += line_val
        else:
            pending_credit_amount += line_val
            pending_count += 1

    # Filter items for display
    if status_filter == "pending":
        display_qs = credit_items_qs.filter(is_paid=False)
    elif status_filter == "paid":
        display_qs = credit_items_qs.filter(is_paid=True)
    else:
        status_filter = "all"
        display_qs = credit_items_qs

    # Pagination: 20 items per page to keep mobile payload minimal
    paginator = Paginator(display_qs, 20)
    try:
        page_obj = paginator.get_page(page_number)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.get_page(1)

    customers = Customer.objects.filter(shopkeeper=request.user).only("id", "name", "phone").order_by("name")

    return render(
        request,
        "khata_app/credit_list.html",
        {
            "items": page_obj,
            "page_obj": page_obj,
            "total_items_count": paginator.count,
            "status_filter": status_filter,
            "customer_id": customer_id,
            "customers": customers,
            "total_credit_amount": total_credit_amount,
            "pending_credit_amount": pending_credit_amount,
            "settled_credit_amount": settled_credit_amount,
            "pending_count": pending_count,
        },
    )
