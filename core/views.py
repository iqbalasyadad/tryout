from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Avg, Q

from exam.models import ExamCategory, Package, Question, Section, UserPackage, Attempt 

def home(request):
    # Statistics for Landing Page
    stats = {
        "categories": ExamCategory.objects.filter(is_active=True).count(),
        "packages": Package.objects.filter(is_active=True).count(),
        "questions": Question.objects.count(),
        # Section needs to be imported, and assume it represents topics/sub-materials
        "sections": Section.objects.count(),
    }
    return render(request, "core/home.html", {"stats": stats})

@login_required
def dashboard(request):
    # Filter
    q = request.GET.get("q", "")
    
    # Paket favorit & purchased
    ups_qs = (
        UserPackage.objects
        .filter(user=request.user)
        .select_related("package", "package__category")
        .order_by("-created_at")
    )

    if q:
        ups_qs = ups_qs.filter(
            Q(package__title__icontains=q) | 
            Q(package__category__name__icontains=q) |
            Q(package__sections__title__icontains=q)
        ).distinct()

    # Convert to list for template usage
    ups = list(ups_qs)

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

    # Statistics
    avg_score = Attempt.objects.filter(
        user=request.user, 
        status=Attempt.Status.SUBMITTED
    ).aggregate(Avg("score"))["score__avg"] or 0

    return render(
        request,
        "core/dashboard.html",
        {
            "favorites": favorites,
            "purchased": purchased,
            "attempts": attempts,
            "in_progress": in_progress,
            "avg_score": round(avg_score, 1),
            "q": q,
        },
    )

@login_required
def settings_view(request):
    user = request.user
    if request.method == "POST":
        # Basic fields
        user.first_name = request.POST.get("first_name", user.first_name)
        user.last_name = request.POST.get("last_name", user.last_name)
        user.email = request.POST.get("email", user.email)
        user.username = request.POST.get("username", user.username)
        
        # Profile fields
        if hasattr(user, "profile"):
            profile = user.profile
        else:
            profile = Profile.objects.create(user=user)
            
        if "avatar" in request.FILES:
            profile.avatar = request.FILES["avatar"]
        
        profile.save()
        user.save()
        
        messages.success(request, "Profile updated successfully.")
        return redirect("settings")

    return render(request, "core/settings.html")


from django.contrib.auth import logout, login
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm

def logout_view_custom(request):
    logout(request)
    return redirect("login")

def signup_view(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("dashboard")
    else:
        form = UserCreationForm()
    return render(request, "registration/signup.html", {"form": form})
