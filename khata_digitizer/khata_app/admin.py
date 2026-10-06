from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ChitItem, Customer, KhataChit, Seller, User


@admin.register(User)
class ShopkeeperAdmin(UserAdmin):
    """
    Extends Django's built-in UserAdmin so shop_name/phone_number/shop_address
    show up in the admin instead of being hidden fields.
    """
    fieldsets = UserAdmin.fieldsets + (
        ("Shop details", {"fields": ("shop_name", "phone_number", "shop_address")}),
    )
    list_display = ("username", "shop_name", "email", "is_staff")


class ScopedToShopkeeperAdmin(admin.ModelAdmin):
    """
    Base admin class that mirrors the "Query Scoping" rule from the rest of
    the app: a non-superuser staff account only ever sees its own shop's
    data in the admin, never another shopkeeper's. Superusers (real site
    admins) still see everything, since they need to for support/debugging.
    """
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(**{self.shopkeeper_lookup: request.user})


class ChitItemInline(admin.TabularInline):
    model = ChitItem
    extra = 0


@admin.register(Customer)
class CustomerAdmin(ScopedToShopkeeperAdmin):
    shopkeeper_lookup = "shopkeeper"
    list_display = ("name", "phone", "shopkeeper", "created_at")
    search_fields = ("name", "phone")


@admin.register(Seller)
class SellerAdmin(ScopedToShopkeeperAdmin):
    shopkeeper_lookup = "shopkeeper"
    list_display = ("name", "phone", "shopkeeper", "created_at")
    search_fields = ("name", "phone")


@admin.register(KhataChit)
class KhataChitAdmin(ScopedToShopkeeperAdmin):
    shopkeeper_lookup = "shopkeeper"
    list_display = ("id", "shopkeeper", "chit_type", "customer", "seller", "upload_date")
    list_filter = ("chit_type", "upload_date")
    inlines = [ChitItemInline]


@admin.register(ChitItem)
class ChitItemAdmin(ScopedToShopkeeperAdmin):
    shopkeeper_lookup = "chit__shopkeeper"
    list_display = ("item_name", "quantity", "price", "is_credit", "is_paid", "paid_at", "chit")
    list_filter = ("is_credit", "is_paid")
    search_fields = ("item_name",)
