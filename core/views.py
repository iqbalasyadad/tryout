from django.shortcuts import render
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from exam.models import Attempt, UserPackage

def home(request):
    return render(request, "core/home.html")

@login_required
def dashboard(request):
    # Paket favorit & purchased
    ups = (
        UserPackage.objects
        .filter(user=request.user)
        .select_related("package", "package__category")
        .order_by("-created_at")
    )

    favorites = [x for x in ups if x.is_favorite]
    purchased = [x for x in ups if x.is_purchased]

    # Attempt history (terbaru)
    attempts = (
        Attempt.objects
        .filter(user=request.user)
        .select_related("package", "package__category")
        .order_by("-created_at")[:50]
    )

    # Attempt yang masih berjalan (buat tombol continue cepat)
    in_progress = (
        Attempt.objects
        .filter(user=request.user, status=Attempt.Status.IN_PROGRESS)
        .select_related("package")
        .order_by("-created_at")[:10]
    )

    return render(
        request,
        "core/dashboard.html",
        {
            "favorites": favorites,
            "purchased": purchased,
            "attempts": attempts,
            "in_progress": in_progress,
        },
    )