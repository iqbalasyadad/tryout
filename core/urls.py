from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("settings/", views.settings_view, name="settings"),
    path("signup/", views.signup_view, name="signup"),
    path("logout-user/", views.logout_view_custom, name="logout_custom"),
]
