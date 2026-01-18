from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Attempt, AttemptAnswer, Choice, Package, Question, UserPackage
from .services import get_remaining_seconds

from .scoring import score_attempt
from .models import Question
from django.http import JsonResponse

from django.contrib import messages
from django.urls import reverse

def _require_package_access(request, package):
    """
    Return redirect response if user doesn't have access.
    Return None if access is allowed.
    """
    if package.is_paid:
        up = UserPackage.objects.filter(user=request.user, package=package).first()
        if not up or not up.is_purchased:
            return redirect("package_detail", slug=package.slug)
    return None

def package_list(request):
    packages = Package.objects.filter(is_active=True).select_related("category")
    return render(request, "exam/package_list.html", {"packages": packages})


def package_detail(request, slug):
    package = get_object_or_404(Package.objects.select_related("category"), slug=slug, is_active=True)
    q_count = package.questions.filter(is_active=True).count()

    up = None
    if request.user.is_authenticated:
        up = UserPackage.objects.filter(user=request.user, package=package).first()

    return render(request, "exam/package_detail.html", {
        "package": package,
        "q_count": q_count,
        "up": up,
    })


@login_required
def start_attempt(request, slug):
    package = get_object_or_404(Package, slug=slug, is_active=True)
    # 🔒 Access control
    guard = _require_package_access(request, package)
    if guard:
        return guard


    mode = request.GET.get("mode", Attempt.Mode.TRYOUT)
    if mode not in (Attempt.Mode.TRYOUT, Attempt.Mode.LEARN):
        mode = Attempt.Mode.TRYOUT

    # Cari attempt yang masih berjalan untuk package+mode ini
    existing = Attempt.objects.filter(
        user=request.user,
        package=package,
        mode=mode,
        status=Attempt.Status.IN_PROGRESS,
    ).order_by("-created_at").first()

    time_info = None
    if existing:
        time_info = get_remaining_seconds(existing)
        # kalau tryout sudah habis, nanti submit otomatis di step berikutnya.
        # untuk sekarang, kita tetap tampilkan sebagai "waktu habis" dan user bisa submit.
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "continue" and existing:
            return redirect("attempt_player", attempt_id=existing.id)

        if action == "new":
            duration_seconds = int(package.duration_minutes) * 60
            attempt = Attempt.objects.create(
                user=request.user,
                package=package,
                mode=mode,
                status=Attempt.Status.IN_PROGRESS,
                duration_seconds=duration_seconds,
                current_index=0,
            )
            return redirect("attempt_player", attempt_id=attempt.id)

    q_count = package.questions.filter(is_active=True).count()
    return render(
        request,
        "exam/start_attempt.html",
        {
            "package": package,
            "mode": mode,
            "existing": existing,
            "q_count": q_count,
            "time_info": time_info,
        },
    )


@login_required
def attempt_player(request, attempt_id: int):
    attempt = get_object_or_404(Attempt, id=attempt_id, user=request.user)

    # 🔒 Access control
    guard = _require_package_access(request, attempt.package)
    if guard:
        return guard
    
    if attempt.status != Attempt.Status.IN_PROGRESS:
        return redirect("attempt_result", attempt_id=attempt.id)

    # get question list
    questions = list(
        Question.objects.filter(package=attempt.package, is_active=True)
        .prefetch_related("choices")
        .order_by("order_index", "id")
    )
    if not questions:
        raise Http404("Paket belum punya soal aktif.")

    # timer info
    time_info = get_remaining_seconds(attempt)

    if attempt.mode == Attempt.Mode.LEARN and attempt.last_active_at is None:
        attempt.last_active_at = timezone.now()
        attempt.save(update_fields=["last_active_at"])

    # Auto-submit jika TRYOUT sudah habis
    if attempt.mode == Attempt.Mode.TRYOUT and time_info.is_expired:
        return redirect("attempt_submit", attempt_id=attempt.id)

    # index
    try:
        idx = int(request.GET.get("q", attempt.current_index))
    except ValueError:
        idx = attempt.current_index
    idx = max(0, min(idx, len(questions) - 1))

    current_question = questions[idx]
    attempt.current_index = idx
    attempt.save(update_fields=["current_index"])

    # ambil/siapkan AttemptAnswer utk current question
    answer_obj, _ = AttemptAnswer.objects.get_or_create(attempt=attempt, question=current_question)

    if request.method == "POST":
        action = request.POST.get("action")  # bisa None kalau user klik jump/nav

        # 1) aksi yang tidak perlu autosave pilihan
        if action == "toggle_flag":
            answer_obj.flagged = not answer_obj.flagged
            answer_obj.save(update_fields=["flagged"])
            return redirect(f"{request.path}?q={idx}")

        if action == "clear":
            with transaction.atomic():
                answer_obj.choices.clear()
                answer_obj.answered_at = None
                answer_obj.save()
            return redirect(f"{request.path}?q={idx}")

        # 2) default: SAVE jawaban sekarang dulu (untuk nav/jump/submit)
        selected_ids = request.POST.getlist("choice")
        with transaction.atomic():
            answer_obj.choices.clear()
            if selected_ids:
                choices = Choice.objects.filter(question=current_question, id__in=selected_ids)
                answer_obj.choices.add(*choices)
                answer_obj.answered_at = timezone.now()
            else:
                answer_obj.answered_at = None
            answer_obj.save()

        # 3) submit
        if action == "submit":
            return redirect("attempt_submit", attempt_id=attempt.id)

        # 4) navigasi prev/next
        nav = request.POST.get("nav")
        if nav == "prev":
            return redirect(f"{request.path}?q={max(0, idx-1)}")
        if nav == "next":
            return redirect(f"{request.path}?q={min(len(questions)-1, idx+1)}")

        # 5) jump dari grid
        jump = request.POST.get("jump")
        if jump is not None:
            try:
                jump_idx = int(jump)
            except ValueError:
                jump_idx = idx
            jump_idx = max(0, min(len(questions) - 1, jump_idx))
            return redirect(f"{request.path}?q={jump_idx}")

        # fallback stay
        return redirect(f"{request.path}?q={idx}")


    # build grid status
    # status:
    # - current: blue
    # - flagged: yellow (prioritas di bawah current)
    # - answered: green
    # - else: red
    answers_map = {
        a.question_id: a
        for a in AttemptAnswer.objects.filter(attempt=attempt, question__in=questions).prefetch_related("choices")
    }

    grid = []
    counts = {"answered": 0, "blank": 0, "flagged": 0, "total": len(questions)}
    for i, q in enumerate(questions):
        a = answers_map.get(q.id)
        is_answered = bool(a and a.choices.all())
        is_flagged = bool(a and a.flagged)

        if is_answered:
            counts["answered"] += 1
        else:
            counts["blank"] += 1
        if is_flagged:
            counts["flagged"] += 1

        if i == idx:
            status = "current"
        elif is_flagged:
            status = "flagged"
        elif is_answered:
            status = "answered"
        else:
            status = "blank"

        grid.append({"num": i + 1, "idx": i, "status": status})

    selected_ids = set(answer_obj.choices.values_list("id", flat=True))
    is_multi = current_question.answer_type in (Question.AnswerType.MULTI,)

    # Build choices_view (khusus LEARN) supaya template bisa highlight tanpa operasi "in"
    choices_view = None
    if attempt.mode == Attempt.Mode.LEARN:
        correct_ids = set(current_question.choices.filter(is_correct=True).values_list("id", flat=True))
        choices_view = []
        for c in current_question.choices.all():
            choices_view.append({
                "id": c.id,
                "label": c.label,
                "text": c.text,
                "image": c.image,
                "audio": c.audio,
                "points": c.points,
                "is_selected": c.id in selected_ids,
                "is_correct": c.id in correct_ids,   # untuk non-weighted
            })

    return render(
        request,
        "exam/attempt_player.html",
        {
            "attempt": attempt,
            "questions": questions,
            "current_question": current_question,
            "idx": idx,
            "grid": grid,
            "counts": counts,
            "selected_ids": selected_ids,
            "is_multi": is_multi,
            "answer_obj": answer_obj,
            "time_info": time_info,
            "choices_view": choices_view,
        },
    )


@login_required
def attempt_submit(request, attempt_id: int):
    attempt = get_object_or_404(Attempt, id=attempt_id, user=request.user)

    # 🔒 Access control
    guard = _require_package_access(request, attempt.package)
    if guard:
        return guard
    
    if attempt.status != Attempt.Status.IN_PROGRESS:
        return redirect("attempt_result", attempt_id=attempt.id)

    questions = list(Question.objects.filter(package=attempt.package, is_active=True).order_by("order_index", "id"))
    answers = AttemptAnswer.objects.filter(attempt=attempt, question__in=questions).prefetch_related("choices")

    answered = 0
    blank = 0
    flagged = 0
    for a in answers:
        if a.flagged:
            flagged += 1
        if a.choices.exists():
            answered += 1

    total = len(questions)
    blank = total - answered

    if request.method == "POST":
        breakdown = score_attempt(attempt)

        attempt.status = Attempt.Status.SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.score = breakdown.total_score
        attempt.max_score = breakdown.max_score
        attempt.save(update_fields=["status", "submitted_at", "score", "max_score"])

        return redirect("attempt_result", attempt_id=attempt.id)


    return render(
        request,
        "exam/attempt_submit.html",
        {
            "attempt": attempt,
            "total": total,
            "answered": answered,
            "blank": blank,
            "flagged": flagged,
        },
    )


@login_required
def attempt_result(request, attempt_id: int):
    attempt = get_object_or_404(Attempt, id=attempt_id, user=request.user)

    # 🔒 Access control
    guard = _require_package_access(request, attempt.package)
    if guard:
        return guard

    questions = list(Question.objects.filter(package=attempt.package, is_active=True).order_by("order_index", "id"))
    answers = AttemptAnswer.objects.filter(attempt=attempt, question__in=questions).prefetch_related("choices")

    answered = 0
    flagged = 0
    for a in answers:
        if a.flagged:
            flagged += 1
        if a.choices.exists():
            answered += 1

    total = len(questions)
    blank = total - answered

    return render(
        request,
        "exam/attempt_result.html",
        {
            "attempt": attempt,
            "total": total,
            "answered": answered,
            "blank": blank,
            "flagged": flagged,
        },
    )


@login_required
def attempt_review(request, attempt_id: int):
    attempt = get_object_or_404(Attempt, id=attempt_id, user=request.user)

    # 🔒 Access control
    guard = _require_package_access(request, attempt.package)
    if guard:
        return guard
    
    questions = list(
        Question.objects.filter(package=attempt.package, is_active=True)
        .prefetch_related("choices")
        .order_by("order_index", "id")
    )
    answers = (
        AttemptAnswer.objects.filter(attempt=attempt, question__in=questions)
        .prefetch_related("choices")
    )
    ans_map = {a.question_id: a for a in answers}

    counts = {"total": len(questions)}

    # index soal
    try:
        idx = int(request.GET.get("q", 0))
    except ValueError:
        idx = 0
    idx = max(0, min(idx, len(questions) - 1))

    q = questions[idx]
    a = ans_map.get(q.id)
    breakdown = score_attempt(attempt)
    q_score = breakdown.per_question.get(q.id, 0)
    q_max = breakdown.per_question_max.get(q.id, 0)

    selected_ids = set(a.choices.values_list("id", flat=True)) if a else set()
    correct_ids = set(q.choices.filter(is_correct=True).values_list("id", flat=True))

    # build pilihan untuk template (tanpa "in" di template)
    choices_view = []
    for c in q.choices.all():
        is_sel = c.id in selected_ids
        is_cor = c.id in correct_ids
        choices_view.append({
            "label": c.label,
            "text": c.text,
            "image": c.image,
            "audio": c.audio,
            "points": c.points,
            "is_selected": is_sel,
            "is_correct": is_cor,
        })

    # grid status
    grid = []
    for i, qq in enumerate(questions):
        aa = ans_map.get(qq.id)
        sel = set(aa.choices.values_list("id", flat=True)) if aa else set()
        cor = set(qq.choices.filter(is_correct=True).values_list("id", flat=True))

        if i == idx:
            status = "current"
        else:
            if not sel:
                status = "blank"
            else:
                status = "answered" if (sel == cor and len(cor) > 0) else "wrong"

        if i != idx and aa and aa.flagged:
            status = "flagged"

        grid.append({"num": i + 1, "idx": i, "status": status})
    
    return render(
        request,
        "exam/attempt_review.html",
        {
            "attempt": attempt,
            "questions": questions,
            "idx": idx,
            "counts": counts,
            "q": q,
            "grid": grid,
            "choices_view": choices_view,
            "q_score": q_score,
            "q_max": q_max,
        },
    )


@login_required
def attempt_autosave(request, attempt_id: int):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)

    attempt = get_object_or_404(Attempt, id=attempt_id, user=request.user)

    # 🔒 Access control
    guard = _require_package_access(request, attempt.package)
    if guard:
        return JsonResponse({"ok": False, "forbidden": True}, status=403)
    
    if attempt.status != Attempt.Status.IN_PROGRESS:
        return JsonResponse({"ok": False, "error": "Attempt not active"}, status=400)

    # Strict tryout: kalau habis, kasih sinyal expired
    time_info = get_remaining_seconds(attempt)
    if attempt.mode == Attempt.Mode.TRYOUT and time_info.is_expired:
        return JsonResponse({"ok": False, "expired": True}, status=200)

    # idx soal yang aktif dikirim oleh client
    try:
        idx = int(request.POST.get("idx", attempt.current_index))
    except ValueError:
        idx = attempt.current_index

    questions = list(
        Question.objects.filter(package=attempt.package, is_active=True)
        .order_by("order_index", "id")
    )
    if not questions:
        return JsonResponse({"ok": False, "error": "No questions"}, status=400)

    idx = max(0, min(len(questions) - 1, idx))
    q = questions[idx]

    answer_obj, _ = AttemptAnswer.objects.get_or_create(attempt=attempt, question=q)

    selected_ids = request.POST.getlist("choice")
    with transaction.atomic():
        answer_obj.choices.clear()
        if selected_ids:
            choices = Choice.objects.filter(question=q, id__in=selected_ids)
            answer_obj.choices.add(*choices)
            answer_obj.answered_at = timezone.now()
        else:
            answer_obj.answered_at = None
        answer_obj.save()

    return JsonResponse({"ok": True, "saved": True})


@login_required
def toggle_favorite(request, slug):
    if request.method != "POST":
        return redirect("package_detail", slug=slug)

    package = get_object_or_404(Package, slug=slug, is_active=True)
    up, _ = UserPackage.objects.get_or_create(user=request.user, package=package)
    up.is_favorite = not up.is_favorite
    up.save(update_fields=["is_favorite"])

    return redirect("package_detail", slug=slug)


@login_required
def purchase_package(request, slug):
    if request.method != "POST":
        return redirect("package_detail", slug=slug)

    package = get_object_or_404(Package, slug=slug, is_active=True)
    up, _ = UserPackage.objects.get_or_create(user=request.user, package=package)

    # MVP: langsung jadi purchased
    up.is_purchased = True
    up.save(update_fields=["is_purchased"])

    return redirect("package_detail", slug=slug)


@login_required
def attempt_heartbeat(request, attempt_id: int):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)

    attempt = get_object_or_404(Attempt, id=attempt_id, user=request.user)

    # 🔒 Access control
    guard = _require_package_access(request, attempt.package)
    if guard:
        return JsonResponse({"ok": False, "forbidden": True}, status=403)
    
    if attempt.status != Attempt.Status.IN_PROGRESS:
        return JsonResponse({"ok": False, "error": "Attempt not active"}, status=400)

    now = timezone.now()

    # Update elapsed_seconds khusus mode LEARN
    if attempt.mode == Attempt.Mode.LEARN:
        # Jika last_active_at belum ada, set dulu (tidak menambah elapsed)
        if attempt.last_active_at is None:
            attempt.last_active_at = now
            attempt.save(update_fields=["last_active_at"])
        else:
            delta = int((now - attempt.last_active_at).total_seconds())
            # Hindari lonjakan besar (mis. tab tidur 2 jam) -> anggap pause
            # Jika user benar-benar idle lama, kita tidak menambah waktu.
            if 0 <= delta <= 30:
                attempt.elapsed_seconds = min(attempt.duration_seconds, attempt.elapsed_seconds + delta)
            attempt.last_active_at = now
            attempt.save(update_fields=["elapsed_seconds", "last_active_at"])

    # Untuk TRYOUT, kita tidak update elapsed_seconds; timer dihitung dari started_at

    time_info = get_remaining_seconds(attempt)
    return JsonResponse({
        "ok": True,
        "remaining_seconds": time_info.remaining_seconds,
        "expired": time_info.is_expired,
        "mode": attempt.mode,
    })
