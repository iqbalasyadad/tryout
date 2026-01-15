from __future__ import annotations
from dataclasses import dataclass
from django.utils import timezone
from .models import Attempt


@dataclass
class AttemptTimeInfo:
    remaining_seconds: int
    is_expired: bool


def get_remaining_seconds(attempt: Attempt) -> AttemptTimeInfo:
    """
    TRYOUT: strict -> remaining = duration - (now - started_at)
    LEARN: pauseable -> remaining = duration - elapsed_seconds (elapsed diupdate manual nanti)
    """
    if attempt.mode == Attempt.Mode.TRYOUT:
        elapsed = int((timezone.now() - attempt.started_at).total_seconds())
    else:
        elapsed = int(attempt.elapsed_seconds)

    remaining = max(0, int(attempt.duration_seconds) - elapsed)
    return AttemptTimeInfo(remaining_seconds=remaining, is_expired=(remaining <= 0))
