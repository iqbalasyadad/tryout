from django.contrib import admin

from .models import (
    ExamCategory,
    Package,
    Section,
    Question,
    Choice,
    Attempt,
    AttemptAnswer,
    UserPackage,
)
from django.urls import path
from django.shortcuts import render, redirect
from django.contrib import messages
from django import forms
from django.db import transaction
import csv
import os
import mimetypes
import urllib.request
from urllib.parse import urlparse
from django.core.files.base import ContentFile


# ---------- Inlines ----------
class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 4
    fields = ("order_index", "label", "text", "image", "audio", "points", "is_correct")
    ordering = ("order_index", "id")
    show_change_link = True


# ---------- Admins ----------
@admin.register(ExamCategory)
class ExamCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "order_index")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("order_index", "name")


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "is_active", "is_paid", "duration_minutes", "order_index")
    list_filter = ("is_active", "is_paid", "category")
    search_fields = ("title",)
    ordering = ("order_index", "title")
    list_editable = ("order_index", "is_active")
    autocomplete_fields = ("category",)


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("title", "package", "order_index")
    list_filter = ("package",)
    search_fields = ("title", "package__title")
    ordering = ("package", "order_index", "title")
    list_editable = ("order_index",)
    autocomplete_fields = ("package",)

VALID_ANSWER_TYPES = {"SINGLE", "MULTI", "WEIGHTED"}

def validate_question_group(rows, line_numbers):

    def _is_valid_http_url(u: str) -> bool:
        u = (u or "").strip()
        return (not u) or u.startswith("http://") or u.startswith("https://")

    for i, r in enumerate(rows):
        ci = (r.get("choice_image_url") or "").strip()
        ca = (r.get("choice_audio_url") or "").strip()

        if ci and not ci.startswith(("http://", "https://")):
            errors.append(f"Invalid choice_image_url at line {line_numbers[i]}")

        if ca and not ca.startswith(("http://", "https://")):
            errors.append(f"Invalid choice_audio_url at line {line_numbers[i]}")


    errors = []
    if not rows:
        return errors

    atype = rows[0].get("answer_type")
    if atype not in VALID_ANSWER_TYPES:
        errors.append(f"Invalid answer_type: {atype}")

    # pastikan field inti konsisten dalam 1 group
    base = rows[0]
    for idx, r in enumerate(rows[1:], start=1):
        for field in ("package_slug", "section_title", "order_index", "answer_type", "stem"):
            if (r.get(field, "") or "") != (base.get(field, "") or ""):
                errors.append(f"Inconsistent '{field}' inside same question group (line {line_numbers[idx]})")
                break

    correct_count = sum(1 for r in rows if str(r.get("is_correct", "0")) == "1")

    if atype == "SINGLE":
        if correct_count != 1:
            errors.append(f"SINGLE must have exactly 1 correct answer (found {correct_count})")
    elif atype == "MULTI":
        if correct_count < 1:
            errors.append("MULTI must have at least 1 correct answer")
    elif atype == "WEIGHTED":
        if correct_count > 0:
            errors.append("WEIGHTED should not use is_correct (set all to 0)")

    for i, r in enumerate(rows):
        if not r.get("stem"):
            errors.append(f"Empty stem at line {line_numbers[i]}")
        if not r.get("choice_label"):
            errors.append(f"Empty choice_label at line {line_numbers[i]}")
        choice_text = (r.get("choice_text") or "").strip()
        choice_img = (r.get("choice_image_url") or "").strip()
        choice_aud = (r.get("choice_audio_url") or "").strip()
        # wajib minimal ada teks ATAU media
        if not choice_text and not choice_img and not choice_aud:
            errors.append(f"Choice must have text or media (line {line_numbers[i]})")

    # optional media url validation (only check scheme)
    img = (rows[0].get("image_url") or "").strip()
    aud = (rows[0].get("audio_url") or "").strip()
    if not _is_valid_http_url(img):
        errors.append(f"Invalid image_url (must start with http/https): {img}")
    if not _is_valid_http_url(aud):
        errors.append(f"Invalid audio_url (must start with http/https): {aud}")

    return errors

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_AUDIO_EXT = {".mp3", ".wav", ".ogg", ".m4a", ".aac"}

def _safe_filename_from_url(url: str, fallback_prefix: str) -> str:
    parsed = urlparse(url)
    base = os.path.basename(parsed.path) or fallback_prefix
    # remove weird chars
    base = "".join(ch for ch in base if ch.isalnum() or ch in ("-", "_", ".", " "))
    base = base.replace(" ", "_")
    if "." not in base:
        base += ".bin"
    return base


def download_to_field(instance, field_name: str, url: str, timeout: int = 15):
    """
    Download URL and save into instance.<field_name> (Django FileField/ImageField).
    Raises ValueError on failure.
    """
    url = (url or "").strip()
    if not url:
        return

    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError(f"Invalid URL for {field_name}: {url}")

    # Download bytes
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "tryout-csv-import/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            content_type = resp.headers.get("Content-Type", "")
    except Exception as e:
        raise ValueError(f"Failed to download {field_name} from {url}: {e}")

    if not data:
        raise ValueError(f"Empty download for {field_name}: {url}")

    filename = _safe_filename_from_url(url, f"{field_name}_{instance.pk or 'new'}")
    ext = os.path.splitext(filename)[1].lower()

    # Validate by extension (basic safety)
    if field_name == "image":
        if ext not in ALLOWED_IMAGE_EXT:
            # try guess from content-type
            guessed_ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
            if guessed_ext.lower() in ALLOWED_IMAGE_EXT:
                filename = os.path.splitext(filename)[0] + guessed_ext
            else:
                raise ValueError(f"Unsupported image extension '{ext}' for URL: {url}")
    if field_name == "audio":
        if ext not in ALLOWED_AUDIO_EXT:
            guessed_ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
            if guessed_ext.lower() in ALLOWED_AUDIO_EXT:
                filename = os.path.splitext(filename)[0] + guessed_ext
            else:
                raise ValueError(f"Unsupported audio extension '{ext}' for URL: {url}")

    # Save to field
    f = ContentFile(data)
    getattr(instance, field_name).save(filename, f, save=False)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    inlines = [ChoiceInline]

    list_display = (
        "short_stem",
        "package",
        "section",
        "answer_type",
        "has_media",
        "is_active",
        "order_index",
    )
    list_filter = ("package", "section", "answer_type", "is_active")
    search_fields = ("stem", "package__title", "section__title")
    ordering = ("package", "order_index", "id")
    list_editable = ("order_index", "is_active")
    autocomplete_fields = ("package", "section")

    fieldsets = (
        ("Konten Soal", {
            "fields": ("package", "section", "order_index", "is_active", "answer_type", "stem", "explanation")
        }),
        ("Media", {"fields": ("image", "audio")}),
    )

    @admin.display(description="Soal")
    def short_stem(self, obj):
        s = (obj.stem or "").strip().replace("\n", " ")
        return s[:70] + ("…" if len(s) > 70 else "")

    @admin.display(description="Media")
    def has_media(self, obj):
        if getattr(obj, "image", None):
            return "IMG"
        if getattr(obj, "audio", None):
            return "AUDIO"
        return "-"

    change_list_template = "admin/question_changelist.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'import-csv/',
                self.admin_site.admin_view(self.import_csv),
                name="exam_question_import_csv",
            ),
        ]
        return custom_urls + urls

    def import_csv(self, request):
        # ===== PHASE 1: PREVIEW =====
        if request.method == "POST" and "confirm" not in request.POST:
            form = CSVImportForm(request.POST, request.FILES)
            if form.is_valid():
                file = request.FILES["csv_file"]
                decoded = file.read().decode("utf-8").splitlines()
                reader = csv.DictReader(decoded)

                grouped = {}   # key_str -> [rows]
                line_map = {}  # key_str -> [line_numbers]

                for i, row in enumerate(reader, start=2):
                    qkey = (row.get("question_key") or "").strip()
                    if qkey:
                        key_str = qkey
                    else:
                        # fallback (tidak ideal), tapi mengurangi risiko stem sama:
                        key_str = f"{row['package_slug']}||{row.get('section_title','')}||{row.get('order_index','')}||{row.get('answer_type','')}||{row.get('stem','')}"

                    grouped.setdefault(key_str, []).append(row)
                    line_map.setdefault(key_str, []).append(i)

                errors = []
                preview = []
                total_choices = 0

                for key_str, rows in grouped.items():
                    errs = validate_question_group(rows, line_map[key_str])
                    if errs:
                        stem = rows[0].get("stem", "")
                        for e in errs:
                            errors.append(f"{stem} (key {key_str}, lines {line_map[key_str]}): {e}")

                    total_choices += len(rows)

                    if len(preview) < 10:
                        preview.append({
                            "stem": rows[0]["stem"],
                            "answer_type": rows[0]["answer_type"],
                            "choice_count": len(rows),
                        })

                # simpan ke session (session-safe: key string)
                request.session["csv_import_data"] = grouped

                context = dict(
                    self.admin_site.each_context(request),
                    title="Preview Import CSV",
                    preview=preview,
                    total_questions=len(grouped),
                    total_choices=total_choices,
                    errors=errors,
                )
                return render(request, "admin/import_questions_preview.html", context)

        # ===== PHASE 2: CONFIRM =====
        if request.method == "POST" and "confirm" in request.POST:
            grouped = request.session.get("csv_import_data")

            if not grouped:
                self.message_user(request, "Session expired. Upload ulang CSV.", level=messages.ERROR)
                return redirect("..")

            try:
                with transaction.atomic():
                    for key_str, rows in grouped.items():
                        row0 = rows[0]
                        package_slug = row0["package_slug"]
                        section_title = (row0.get("section_title") or "").strip()
                        stem = row0.get("stem", "")


                        try:
                            package = Package.objects.get(slug=package_slug)
                        except Package.DoesNotExist:
                            raise ValueError(f"Package not found: {package_slug}")

                        section = None
                        if section_title:
                            section, _ = Section.objects.get_or_create(
                                title=section_title,
                                package=package,
                                defaults={"order_index": 0},
                            )

                        q = Question.objects.create(
                            package=package,
                            section=section,
                            stem=stem,
                            explanation=row0.get("explanation", ""),
                            answer_type=row0["answer_type"],
                            order_index=int(row0.get("order_index") or 0),
                            is_active=True,
                        )

                        # Import media (optional) from URLs
                        image_url = (row0.get("image_url") or "").strip()
                        audio_url = (row0.get("audio_url") or "").strip()

                        if image_url:
                            download_to_field(q, "image", image_url)

                        if audio_url:
                            download_to_field(q, "audio", audio_url)

                        # save q once after attaching files
                        q.save()

                        for r in rows:
                            choice = Choice.objects.create(
                                question=q,
                                label=r.get("choice_label", ""),
                                text=r.get("choice_text", ""),
                                points=int(r.get("choice_points") or 0),
                                is_correct=str(r.get("is_correct", "0")) == "1",
                            )

                            # import choice media
                            cimg = (r.get("choice_image_url") or "").strip()
                            caud = (r.get("choice_audio_url") or "").strip()

                            if cimg:
                                download_to_field(choice, "image", cimg)

                            if caud:
                                download_to_field(choice, "audio", caud)

                            choice.save()


                del request.session["csv_import_data"]
                self.message_user(request, "Import CSV berhasil!", level=messages.SUCCESS)
                return redirect("..")

            except Exception as e:
                self.message_user(request, f"Error saat import: {e}", level=messages.ERROR)
                return redirect("..")

        # ===== UPLOAD FORM =====
        form = CSVImportForm()
        context = dict(
            self.admin_site.each_context(request),
            form=form,
            title="Import Questions from CSV",
        )
        return render(request, "admin/import_questions_csv.html", context)


@admin.register(Choice)
class ChoiceAdmin(admin.ModelAdmin):
    list_display = ("question", "order_index", "label", "text_short", "has_media", "points", "is_correct")
    list_filter = ("is_correct", "question__package", "question__answer_type")
    search_fields = ("label", "text", "question__stem", "question__package__title")
    ordering = ("question", "order_index", "id")
    list_editable = ("order_index", "is_correct", "points")

    @admin.display(description="Text")
    def text_short(self, obj):
        t = (obj.text or "").strip().replace("\n", " ")
        return t[:50] + ("…" if len(t) > 50 else "")
    
    @admin.display(description="Media")
    def has_media(self, obj):
        if obj.image:
            return "IMG"
        if obj.audio:
            return "AUDIO"
        return "-"


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "package", "mode", "status", "score", "created_at")
    list_filter = ("mode", "status", "package")
    search_fields = ("user__username", "package__title")
    ordering = ("-created_at",)


@admin.register(AttemptAnswer)
class AttemptAnswerAdmin(admin.ModelAdmin):
    list_display = ("attempt", "question", "flagged", "answered_at")
    list_filter = ("flagged", "attempt__package")
    search_fields = ("attempt__user__username", "question__stem")
    ordering = ("-answered_at",)


@admin.register(UserPackage)
class UserPackageAdmin(admin.ModelAdmin):
    list_display = ("user", "package", "is_favorite", "is_purchased", "created_at")
    list_filter = ("is_favorite", "is_purchased", "package")
    search_fields = ("user__username", "package__title")
    ordering = ("-created_at",)

class CSVImportForm(forms.Form):
    csv_file = forms.FileField()