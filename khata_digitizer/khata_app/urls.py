from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from . import views

from .forms import ShopkeeperAuthenticationForm

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="dashboard", permanent=False), name="home"),
    path("register/", views.register, name="register"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="khata_app/login.html",
            authentication_form=ShopkeeperAuthenticationForm,
        ),
        name="login",
    ),
    path("logout/", views.user_logout, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("chits/upload/", views.chit_upload, name="chit_upload"),
    path("chits/<uuid:chit_id>/", views.chit_detail, name="chit_detail"),
    path("chits/<uuid:chit_id>/review/", views.chit_review, name="chit_review"),
    path("chits/<uuid:chit_id>/edit/", views.chit_edit, name="chit_edit"),
    path("credit/", views.credit_list, name="credit_list"),
    path("items/<uuid:item_id>/toggle-paid/", views.item_toggle_paid, name="item_toggle_paid"),
]
