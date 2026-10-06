import os
import re
from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.forms import modelformset_factory

from .models import ChitItem, Customer, KhataChit, Seller, User


class ShopkeeperRegistrationForm(UserCreationForm):
    """
    Registration form for shopkeepers.
    Requires an authentic 11-digit Pakistani mobile number (e.g. 03001234567).
    """

    shop_name = forms.CharField(
        required=True,
        max_length=255,
        label="Shop Name",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. Al-Madina Kiryana Store",
        }),
    )
    username = forms.CharField(
        required=True,
        max_length=150,
        label="Username",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. almadina_store",
        }),
        help_text="Unique store ID for sign-in (letters, numbers, and underscores).",
    )
    phone_number = forms.CharField(
        required=True,
        max_length=11,
        min_length=11,
        label="Mobile Number (Pakistan – Exactly 11 Digits)",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace",
            "placeholder": "03001234567",
            "autocomplete": "tel",
            "inputmode": "numeric",
            "maxlength": "11",
            "pattern": "03[0-9]{9}",
            "oninput": "let v = this.value.replace(/[^0-9+]/g, ''); if(v.startsWith('+92')) v = '0' + v.substring(3); else if(v.startsWith('92') && v.length > 11) v = '0' + v.substring(2); this.value = v.replace(/[^0-9]/g, '').slice(0, 11);",
        }),
        help_text="Pakistani mobile numbers are strictly 11 digits starting with 03 (e.g. 03001234567). Cannot exceed 11 digits.",
    )
    email = forms.EmailField(
        required=False,
        label="Email Address (Optional)",
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "store@example.com",
        }),
    )
    shop_address = forms.CharField(
        required=False,
        max_length=255,
        label="Shop Address (Optional)",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. Main Bazar, Lahore",
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if "class" not in field.widget.attrs:
                field.widget.attrs["class"] = "form-control"

    def clean_phone_number(self):
        raw = self.cleaned_data.get("phone_number", "")
        cleaned = re.sub(r'[\s\-\(\)\.]', '', str(raw).strip())

        # Normalize country codes to local 11-digit format starting with 0
        if cleaned.startswith('+92'):
            cleaned = '0' + cleaned[3:]
        elif cleaned.startswith('0092'):
            cleaned = '0' + cleaned[4:]
        elif cleaned.startswith('92') and len(cleaned) == 12:
            cleaned = '0' + cleaned[2:]
        elif cleaned.startswith('3') and len(cleaned) == 10:
            cleaned = '0' + cleaned

        if not cleaned.isdigit():
            raise forms.ValidationError("Mobile number must contain digits only.")

        if len(cleaned) != 11:
            raise forms.ValidationError(
                f"Pakistani mobile numbers must be exactly 11 digits (e.g. 03001234567). You entered {len(cleaned)} digits."
            )

        # Valid Pakistani mobile codes: 0300 to 0349, and 0355
        if not re.match(r'^03[0-5][0-9]{8}$', cleaned):
            raise forms.ValidationError(
                "Please enter a valid Pakistani mobile number starting with 03 (e.g. 0300, 0301, 0312, 0321, 0333, 0345)."
            )

        # Reject common dummy / placeholder numbers
        dummy_numbers = {
            "03000000000", "03111111111", "03222222222", "03333333333",
            "03444444444", "03555555555", "03123456789", "03012345678",
            "03987654321", "03001234567", "03111234567", "03211234567"
        }
        if cleaned in dummy_numbers:
            raise forms.ValidationError("Please provide your real active mobile number rather than a placeholder.")

        # Reject repetitive dummy numbers (e.g. 03020000000)
        subscriber_digits = cleaned[4:]
        if len(set(subscriber_digits)) <= 2:
            raise forms.ValidationError("Please provide a real active mobile number.")

        if User.objects.filter(phone_number=cleaned).exists():
            raise forms.ValidationError("An account with this mobile number already exists.")

        return cleaned

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "shop_name",
            "username",
            "phone_number",
            "email",
            "shop_address",
        )


class ShopkeeperAuthenticationForm(AuthenticationForm):
    """
    Shopkeeper login form allowing sign-in with either Username or Pakistani Mobile Number.
    """
    username = forms.CharField(
        label="Username or Mobile Number",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Enter username or 03xxxxxxxxx",
            "autofocus": True,
        }),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Enter your password",
            "autocomplete": "current-password",
        }),
    )

    def clean(self):
        username_or_phone = self.cleaned_data.get("username", "").strip()
        password = self.cleaned_data.get("password")

        if username_or_phone and password:
            # Check if username_or_phone looks like a phone number
            normalized = re.sub(r'[\s\-\(\)\.]', '', username_or_phone)
            if normalized.startswith('+92'):
                normalized = '0' + normalized[3:]
            elif normalized.startswith('0092'):
                normalized = '0' + normalized[4:]
            elif normalized.startswith('92') and len(normalized) == 12:
                normalized = '0' + normalized[2:]
            elif normalized.startswith('3') and len(normalized) == 10:
                normalized = '0' + normalized

            user_obj = None
            if normalized.isdigit() and len(normalized) == 11:
                user_obj = User.objects.filter(phone_number=normalized).first()

            if user_obj:
                self.user_cache = authenticate(
                    self.request,
                    username=user_obj.username,
                    password=password,
                )
            else:
                self.user_cache = authenticate(
                    self.request,
                    username=username_or_phone,
                    password=password,
                )

            if self.user_cache is None:
                raise self.get_invalid_login_error()
            else:
                self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data


class ChitUploadForm(forms.ModelForm):
    """
    Upload form for a photographed Khata chit.
    Allows specifying whether this chit is from a Customer (sale / credit)
    or a Seller/Supplier (inventory purchase), with direct name entry or
    existing dropdown selection.
    """

    new_customer_name = forms.CharField(
        required=False,
        max_length=255,
        label="Customer Name",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Enter customer name (e.g. Ali Ahmed)",
            "id": "newCustomerNameInput",
        }),
    )
    new_customer_phone = forms.CharField(
        required=False,
        max_length=20,
        label="Customer Phone (Optional)",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. 03001234567",
            "id": "newCustomerPhoneInput",
        }),
    )
    new_seller_name = forms.CharField(
        required=False,
        max_length=255,
        label="Seller / Supplier Name",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Enter seller/vendor name (e.g. Metro Cash & Carry, Rice Wholesaler)",
            "id": "newSellerNameInput",
        }),
    )
    new_seller_phone = forms.CharField(
        required=False,
        max_length=20,
        label="Seller Phone (Optional)",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. 03211234567",
            "id": "newSellerPhoneInput",
        }),
    )

    class Meta:
        model = KhataChit
        fields = ["chit_type", "customer", "seller", "image"]
        widgets = {
            "chit_type": forms.RadioSelect(attrs={"class": "btn-check"}),
            "customer": forms.Select(attrs={"class": "form-select", "id": "customerSelectInput"}),
            "seller": forms.Select(attrs={"class": "form-select", "id": "sellerSelectInput"}),
            "image": forms.FileInput(attrs={"class": "form-control", "accept": "image/*", "id": "chitImageInput"}),
        }

    def __init__(self, *args, shopkeeper=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.shopkeeper = shopkeeper
        self.fields["customer"].required = False
        self.fields["seller"].required = False
        self.fields["chit_type"].initial = "customer"
        if shopkeeper is not None:
            self.fields["customer"].queryset = Customer.objects.filter(shopkeeper=shopkeeper)
            self.fields["seller"].queryset = Seller.objects.filter(shopkeeper=shopkeeper)

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if not image:
            raise forms.ValidationError("Please upload a chit photo.")

        # Enforce max file size: 10 MB limit
        max_size = 10 * 1024 * 1024
        if image.size > max_size:
            raise forms.ValidationError(
                f"Image file size cannot exceed 10 MB. Uploaded size: {image.size / (1024 * 1024):.1f} MB."
            )

        # Enforce allowed image extensions
        allowed_extensions = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
        ext = os.path.splitext(image.name)[1].lower()
        if ext not in allowed_extensions:
            raise forms.ValidationError(
                f"Unsupported file format '{ext}'. Allowed image formats: JPG, JPEG, PNG, WEBP, HEIC."
            )

        # Verify image integrity and prevent polyglots using PIL
        try:
            from PIL import Image
            img = Image.open(image)
            img.verify()
            image.seek(0)
        except Exception:
            raise forms.ValidationError("Uploaded file is corrupted or not a valid image.")

        return image

    def save(self, commit=True):
        chit = super().save(commit=False)
        if self.shopkeeper:
            chit.shopkeeper = self.shopkeeper

        chit_type = self.cleaned_data.get("chit_type") or "customer"
        chit.chit_type = chit_type

        if chit_type == "customer":
            chit.seller = None
            cust_name = (self.cleaned_data.get("new_customer_name") or "").strip()
            cust_phone = (self.cleaned_data.get("new_customer_phone") or "").strip()
            if cust_name and self.shopkeeper:
                customer, _ = Customer.objects.get_or_create(
                    shopkeeper=self.shopkeeper,
                    name=cust_name,
                    defaults={"phone": cust_phone},
                )
                if cust_phone and not customer.phone:
                    customer.phone = cust_phone
                    customer.save(update_fields=["phone"])
                chit.customer = customer
            elif self.cleaned_data.get("customer"):
                chit.customer = self.cleaned_data.get("customer")
        else:
            chit.customer = None
            seller_name = (self.cleaned_data.get("new_seller_name") or "").strip()
            seller_phone = (self.cleaned_data.get("new_seller_phone") or "").strip()
            if seller_name and self.shopkeeper:
                seller, _ = Seller.objects.get_or_create(
                    shopkeeper=self.shopkeeper,
                    name=seller_name,
                    defaults={"phone": seller_phone},
                )
                if seller_phone and not seller.phone:
                    seller.phone = seller_phone
                    seller.save(update_fields=["phone"])
                chit.seller = seller
            elif self.cleaned_data.get("seller"):
                chit.seller = self.cleaned_data.get("seller")

        if commit:
            chit.save()
        return chit


class ChitPartyUpdateForm(forms.ModelForm):
    """Allows updating party details (Customer vs Seller) for an existing chit."""
    new_customer_name = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Or enter new customer name"}),
        label="New Customer Name",
    )
    new_seller_name = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Or enter new seller name"}),
        label="New Seller Name",
    )

    class Meta:
        model = KhataChit
        fields = ["chit_type", "customer", "seller"]
        widgets = {
            "chit_type": forms.Select(attrs={"class": "form-select", "id": "chitTypeSelect"}),
            "customer": forms.Select(attrs={"class": "form-select"}),
            "seller": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, shopkeeper=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.shopkeeper = shopkeeper
        self.fields["customer"].required = False
        self.fields["seller"].required = False
        if shopkeeper is not None:
            self.fields["customer"].queryset = Customer.objects.filter(shopkeeper=shopkeeper)
            self.fields["seller"].queryset = Seller.objects.filter(shopkeeper=shopkeeper)

    def save(self, commit=True):
        chit = super().save(commit=False)
        chit_type = self.cleaned_data.get("chit_type") or "customer"
        chit.chit_type = chit_type

        if chit_type == "customer":
            chit.seller = None
            cust_name = (self.cleaned_data.get("new_customer_name") or "").strip()
            if cust_name and self.shopkeeper:
                customer, _ = Customer.objects.get_or_create(
                    shopkeeper=self.shopkeeper,
                    name=cust_name,
                )
                chit.customer = customer
            elif self.cleaned_data.get("customer"):
                chit.customer = self.cleaned_data.get("customer")
        else:
            chit.customer = None
            seller_name = (self.cleaned_data.get("new_seller_name") or "").strip()
            if seller_name and self.shopkeeper:
                seller, _ = Seller.objects.get_or_create(
                    shopkeeper=self.shopkeeper,
                    name=seller_name,
                )
                chit.seller = seller
            elif self.cleaned_data.get("seller"):
                chit.seller = self.cleaned_data.get("seller")

        if commit:
            chit.save()
        return chit


class ChitItemForm(forms.ModelForm):
    """One reviewable/editable line item extracted from a chit."""

    quantity = forms.FloatField(required=False, initial=None)

    class Meta:
        model = ChitItem
        fields = ["item_name", "quantity", "price", "cost_price", "is_credit", "is_paid"]
        widgets = {
            "item_name": forms.TextInput(attrs={"class": "form-control"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "cost_price": forms.NumberInput(attrs={
                "class": "form-control", "step": "0.01",
                "placeholder": "optional",
            }),
            "is_credit": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_paid": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_quantity(self):
        return self.cleaned_data.get("quantity") or 1


ChitItemFormSet = modelformset_factory(
    ChitItem, form=ChitItemForm, extra=3, can_delete=True
)

ChitItemEditFormSet = modelformset_factory(
    ChitItem, form=ChitItemForm, extra=2, can_delete=True
)
