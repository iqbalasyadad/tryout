from django.conf import settings
from django.db import models
from django.utils.text import slugify


class ExamCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    is_active = models.BooleanField(default=True)
    order_index = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order_index", "name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Package(models.Model):
    category = models.ForeignKey(ExamCategory, on_delete=models.PROTECT, related_name="packages")
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)

    description = models.TextField(blank=True)
    is_paid = models.BooleanField(default=False)
    price = models.PositiveIntegerField(default=0)  # rupiah (opsional, MVP)
    duration_minutes = models.PositiveIntegerField(default=90)

    is_active = models.BooleanField(default=True)
    order_index = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order_index", "title"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200] or "package"
            slug = base
            i = 1
            while Package.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class Section(models.Model):
    """
    Contoh: TWK/TIU/TKP, Listening/Reading, Fisika/Kalkulus.
    Optional tapi sangat berguna untuk breakdown.
    """
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField(max_length=120)
    order_index = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order_index", "id"]
        unique_together = [("package", "title")]

    def __str__(self):
        return f"{self.package.title} - {self.title}"


class Question(models.Model):
    class ContentType(models.TextChoices):
        TEXT = "TEXT", "Text"
        IMAGE = "IMAGE", "Image"
        AUDIO = "AUDIO", "Audio"
        MIXED = "MIXED", "Mixed"  # text + image/audio

    class AnswerType(models.TextChoices):
        SINGLE = "SINGLE", "Single Choice"
        MULTI = "MULTI", "Multiple Choice"
        TRUE_FALSE = "TRUE_FALSE", "True/False"
        WEIGHTED = "WEIGHTED", "Weighted (points per option)"

    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="questions")
    section = models.ForeignKey(Section, on_delete=models.SET_NULL, null=True, blank=True, related_name="questions")

    order_index = models.PositiveIntegerField(default=0)

    content_type = models.CharField(max_length=10, choices=ContentType.choices, default=ContentType.TEXT)
    answer_type = models.CharField(max_length=15, choices=AnswerType.choices, default=AnswerType.SINGLE)

    stem = models.TextField()  # teks pertanyaan

    image = models.ImageField(upload_to="questions/images/", null=True, blank=True)
    audio = models.FileField(upload_to="questions/audio/", null=True, blank=True)

    explanation = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order_index", "id"]

    def __str__(self):
        return f"Q{self.id} - {self.package.title}"


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
    label = models.CharField(max_length=5, blank=True)  # A/B/C/D (opsional)
    text = models.TextField(blank=True)

    image = models.ImageField(upload_to="choices/images/", null=True, blank=True)
    audio = models.FileField(upload_to="choices/audio/", null=True, blank=True)

    is_correct = models.BooleanField(default=False)
    points = models.IntegerField(default=0)  # untuk WEIGHTED / scoring khusus

    order_index = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order_index", "id"]

    def __str__(self):
        return f"{self.question_id} - {self.label or 'choice'}"


class UserPackage(models.Model):
    """
    Menyimpan status user: favorited / purchased.
    MVP: purchased boolean dulu.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_packages")
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="user_packages")

    is_favorite = models.BooleanField(default=False)
    is_purchased = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "package")]

    def __str__(self):
        return f"{self.user} - {self.package}"


class Attempt(models.Model):
    class Mode(models.TextChoices):
        TRYOUT = "TRYOUT", "Tryout"
        LEARN = "LEARN", "Learn"

    class Status(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        SUBMITTED = "SUBMITTED", "Submitted"
        EXPIRED = "EXPIRED", "Expired"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts")
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="attempts")

    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.TRYOUT)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.IN_PROGRESS)

    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    # timer
    duration_seconds = models.PositiveIntegerField(default=90 * 60)  # snapshot dari package
    elapsed_seconds = models.PositiveIntegerField(default=0)  # khusus mode LEARN (pauseable)

    current_index = models.PositiveIntegerField(default=0)  # untuk resume ke nomor terakhir dibuka

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    score = models.IntegerField(default=0)
    max_score = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user} - {self.package} - {self.mode} - {self.status}"


class AttemptAnswer(models.Model):
    """
    Jawaban per soal pada attempt.
    - choices: multi-select (untuk single/multi/true-false juga bisa)
    - flagged: ragu-ragu
    """
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="attempt_answers")
    choices = models.ManyToManyField(Choice, blank=True, related_name="attempt_answers")

    flagged = models.BooleanField(default=False)
    answered_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("attempt", "question")]

    def __str__(self):
        return f"{self.attempt_id} - Q{self.question_id}"
