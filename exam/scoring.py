from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from .models import Attempt, AttemptAnswer, Choice, Question


@dataclass
class ScoreBreakdown:
    total_score: int
    max_score: int
    per_question: Dict[int, int]       # question_id -> score
    per_question_max: Dict[int, int]   # question_id -> max


def _set_equals(a: Set[int], b: Set[int]) -> bool:
    return a == b


def score_attempt(attempt: Attempt) -> ScoreBreakdown:
    """
    Rules (MVP, bisa kamu ubah nanti):
    - SINGLE / TRUE_FALSE:
        +1 jika pilihan benar, 0 jika salah/kosong
        max per soal = 1
    - MULTI:
        +1 jika set pilihan user == set pilihan benar, else 0
        max per soal = 1
    - WEIGHTED:
        skor = sum(points pilihan yang dipilih)
        max per soal = sum(points pilihan benar) (atau bisa aturan lain)
    """
    questions: List[Question] = list(
        Question.objects.filter(package=attempt.package, is_active=True).prefetch_related("choices")
        .order_by("order_index", "id")
    )

    answers = (
        AttemptAnswer.objects.filter(attempt=attempt, question__in=questions)
        .prefetch_related("choices")
    )
    ans_map: Dict[int, AttemptAnswer] = {a.question_id: a for a in answers}

    total_score = 0
    max_score = 0
    per_question: Dict[int, int] = {}
    per_question_max: Dict[int, int] = {}

    for q in questions:
        a = ans_map.get(q.id)
        selected_ids: Set[int] = set(a.choices.values_list("id", flat=True)) if a else set()

        choices: List[Choice] = list(q.choices.all())
        correct_ids = {c.id for c in choices if c.is_correct}

        if q.answer_type in (Question.AnswerType.SINGLE, Question.AnswerType.TRUE_FALSE):
            # treat as single
            q_max = 1
            q_score = 1 if (len(selected_ids) == 1 and next(iter(selected_ids)) in correct_ids) else 0

        elif q.answer_type == Question.AnswerType.MULTI:
            q_max = 1
            q_score = 1 if _set_equals(selected_ids, correct_ids) and len(correct_ids) > 0 else 0

        elif q.answer_type == Question.AnswerType.WEIGHTED:
            # sum points of selected
            selected_points = sum(c.points for c in choices if c.id in selected_ids)
            correct_points = sum(c.points for c in choices if c.is_correct)
            q_score = int(selected_points)
            q_max = int(correct_points)

        else:
            # fallback: single rule
            q_max = 1
            q_score = 1 if (len(selected_ids) == 1 and next(iter(selected_ids)) in correct_ids) else 0

        per_question[q.id] = q_score
        total_score += q_score
        max_score += q_max
        per_question_max[q.id] = q_max

    return ScoreBreakdown(
        total_score=total_score,
        max_score=max_score,
        per_question=per_question,
        per_question_max=per_question_max
    )
