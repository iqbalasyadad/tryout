from django.contrib import admin
from .models import (
    ExamCategory, Package, Section, Question, Choice,
    UserPackage, Attempt, AttemptAnswer
)

class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 4

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "package", "section", "answer_type", "content_type", "order_index", "is_active")
    list_filter = ("package", "answer_type", "content_type", "is_active")
    search_fields = ("stem",)
    ordering = ("package", "order_index", "id")
    inlines = [ChoiceInline]

@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "duration_minutes", "is_paid", "price", "is_active", "order_index")
    list_filter = ("category", "is_paid", "is_active")
    search_fields = ("title",)
    prepopulated_fields = {"slug": ("title",)}

@admin.register(ExamCategory)
class ExamCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "order_index")
    prepopulated_fields = {"slug": ("name",)}

@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("title", "package", "order_index")
    list_filter = ("package",)

admin.site.register(Choice)
admin.site.register(UserPackage)
admin.site.register(Attempt)
admin.site.register(AttemptAnswer)
