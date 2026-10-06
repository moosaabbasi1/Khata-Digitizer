from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .analytics import compute_dashboard_totals
from .models import ChitItem, Customer, KhataChit

User = get_user_model()


class AnalyticsAndCreditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="shopkeeper1",
            password="testpassword123",
            shop_name="Moosa Kiryana",
        )
        self.customer = Customer.objects.create(
            shopkeeper=self.user,
            name="Ali Ahmed",
            phone="03001234567",
        )
        self.chit = KhataChit.objects.create(
            shopkeeper=self.user,
            customer=self.customer,
        )

    def test_analytics_totals_with_credit_and_paid_credit(self):
        # Item 1: Cash item: 2 x 100 = 200
        ChitItem.objects.create(
            chit=self.chit,
            item_name="Rice 1kg",
            quantity=2,
            price=Decimal("100.00"),
            cost_price=Decimal("80.00"),
            is_credit=False,
            is_paid=False,
        )
        # Item 2: Unpaid credit item: 1 x 240 = 240
        credit_unpaid = ChitItem.objects.create(
            chit=self.chit,
            item_name="Sugar 2kg",
            quantity=1,
            price=Decimal("240.00"),
            cost_price=Decimal("200.00"),
            is_credit=True,
            is_paid=False,
        )
        # Item 3: Paid credit item (settled later): 1 x 150 = 150
        ChitItem.objects.create(
            chit=self.chit,
            item_name="Cooking Oil",
            quantity=1,
            price=Decimal("150.00"),
            cost_price=Decimal("120.00"),
            is_credit=True,
            is_paid=True,
        )

        items_qs = ChitItem.objects.filter(chit=self.chit)
        totals = compute_dashboard_totals(items_qs)

        # Total sales = 200 + 240 + 150 = 590
        self.assertEqual(totals.total_sales, Decimal("590.00"))
        # Pending credit should ONLY be the unpaid credit item = 240
        self.assertEqual(totals.total_credit_pending, Decimal("240.00"))
        # Received should be total_sales - pending_credit = 590 - 240 = 350
        # (200 cash + 150 settled credit)
        self.assertEqual(totals.total_paid, Decimal("350.00"))

        # Now simulate customer paying off the remaining 240 credit item
        credit_unpaid.is_paid = True
        credit_unpaid.save()

        totals_after_payment = compute_dashboard_totals(items_qs)
        self.assertEqual(totals_after_payment.total_sales, Decimal("590.00"))
        self.assertEqual(totals_after_payment.total_credit_pending, Decimal("0.00"))
        self.assertEqual(totals_after_payment.total_paid, Decimal("590.00"))


class ViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="shopkeeper1",
            password="testpassword123",
            shop_name="Moosa Kiryana",
        )
        self.other_user = User.objects.create_user(
            username="other_shopkeeper",
            password="testpassword123",
            shop_name="Other Shop",
        )
        self.customer = Customer.objects.create(
            shopkeeper=self.user,
            name="Ali Ahmed",
        )
        self.chit = KhataChit.objects.create(
            shopkeeper=self.user,
            customer=self.customer,
        )
        self.credit_item = ChitItem.objects.create(
            chit=self.chit,
            item_name="Tea Pack",
            quantity=1,
            price=Decimal("180.00"),
            is_credit=True,
            is_paid=False,
        )

    def test_logout_view_handles_both_get_and_post_without_405(self):
        self.client.login(username="shopkeeper1", password="testpassword123")
        # GET request to logout must NOT return 405 Method Not Allowed
        response_get = self.client.get(reverse("logout"))
        self.assertRedirects(response_get, reverse("login"))

        # Re-login and test POST
        self.client.login(username="shopkeeper1", password="testpassword123")
        response_post = self.client.post(reverse("logout"))
        self.assertRedirects(response_post, reverse("login"))

    def test_item_toggle_paid(self):
        self.client.login(username="shopkeeper1", password="testpassword123")
        self.assertFalse(self.credit_item.is_paid)

        # Toggle to paid
        response = self.client.post(
            reverse("item_toggle_paid", args=[self.credit_item.id]),
            {"next": reverse("dashboard")},
        )
        self.assertRedirects(response, reverse("dashboard"))

        self.credit_item.refresh_from_db()
        self.assertTrue(self.credit_item.is_paid)
        self.assertIsNotNone(self.credit_item.paid_at)

        # Toggle back to unpaid
        self.client.post(
            reverse("item_toggle_paid", args=[self.credit_item.id]),
            {"next": reverse("dashboard")},
        )
        self.credit_item.refresh_from_db()
        self.assertFalse(self.credit_item.is_paid)
        self.assertIsNone(self.credit_item.paid_at)

    def test_item_toggle_paid_cross_tenant_forbidden(self):
        # Other user cannot modify shopkeeper1's item
        self.client.login(username="other_shopkeeper", password="testpassword123")
        response = self.client.post(reverse("item_toggle_paid", args=[self.credit_item.id]))
        self.assertEqual(response.status_code, 404)

    def test_credit_list_view(self):
        self.client.login(username="shopkeeper1", password="testpassword123")
        response = self.client.get(reverse("credit_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tea Pack")
        self.assertContains(response, "Ali Ahmed")

    def test_chit_detail_view(self):
        self.client.login(username="shopkeeper1", password="testpassword123")
        response = self.client.get(reverse("chit_detail", args=[self.chit.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tea Pack")


class ShopkeeperRegistrationAndPhoneTests(TestCase):
    def test_valid_pakistani_phone_registration_form(self):
        from khata_app.forms import ShopkeeperRegistrationForm
        form_data = {
            "shop_name": "Hamza Kiryana",
            "username": "hamza_store",
            "phone_number": "03028475923",
            "password": "StrongPassword123!",
            "password2": "StrongPassword123!",
        }
        form = ShopkeeperRegistrationForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["phone_number"], "03028475923")

    def test_pakistani_phone_normalization_with_country_code(self):
        from khata_app.forms import ShopkeeperRegistrationForm
        form_data = {
            "shop_name": "Hamza Kiryana",
            "username": "hamza_store_2",
            "phone_number": "+92 345 7128493",
            "password": "StrongPassword123!",
            "password2": "StrongPassword123!",
        }
        form = ShopkeeperRegistrationForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["phone_number"], "03457128493")

    def test_invalid_and_dummy_phone_numbers_rejected(self):
        from khata_app.forms import ShopkeeperRegistrationForm
        invalid_numbers = [
            "03001234567",   # placeholder
            "03000000000",   # dummy identical
            "03123456789",   # sequential dummy
            "04231234567",   # landline prefix
            "0302123",       # too short
            "12345678901",   # not starting with 03
        ]
        for num in invalid_numbers:
            form_data = {
                "shop_name": "Test Shop",
                "username": f"user_{num[-4:]}",
                "phone_number": num,
                "password": "StrongPassword123!",
                "password2": "StrongPassword123!",
            }
            form = ShopkeeperRegistrationForm(data=form_data)
            self.assertFalse(form.is_valid(), f"Phone {num} should be rejected")
            self.assertIn("phone_number", form.errors)

    def test_login_with_phone_number(self):
        User.objects.create_user(
            username="kashif_shop",
            phone_number="03219876543",
            password="testpassword123",
            shop_name="Kashif Traders",
        )
        # Login using mobile number instead of username
        logged_in = self.client.login(username="03219876543", password="testpassword123")
        # Standard client.login uses Django's ModelBackend which by default checks username;
        # Our custom ShopkeeperAuthenticationForm allows mobile in LoginView:
        response = self.client.post(reverse("login"), {
            "username": "03219876543",
            "password": "testpassword123",
        })
        self.assertRedirects(response, reverse("dashboard"))

