from django.urls import path
from . import views

urlpatterns = [
    path("packages/", views.package_list, name="package_list"),
    path("packages/<slug:slug>/", views.package_detail, name="package_detail"),
    path("packages/<slug:slug>/start/", views.start_attempt, name="start_attempt"),
    path("attempts/<int:attempt_id>/", views.attempt_player, name="attempt_player"),
    path("attempts/<int:attempt_id>/submit/", views.attempt_submit, name="attempt_submit"),
    path("attempts/<int:attempt_id>/result/", views.attempt_result, name="attempt_result"),
    path("attempts/<int:attempt_id>/review/", views.attempt_review, name="attempt_review"),
    path("attempts/<int:attempt_id>/autosave/", views.attempt_autosave, name="attempt_autosave"),
    path("packages/<slug:slug>/favorite/", views.toggle_favorite, name="toggle_favorite"),
    path("packages/<slug:slug>/purchase/", views.purchase_package, name="purchase_package"),
    path("attempts/<int:attempt_id>/heartbeat/", views.attempt_heartbeat, name="attempt_heartbeat"),

]
