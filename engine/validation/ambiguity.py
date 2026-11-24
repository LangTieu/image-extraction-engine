"""Confusable-character handling (P5 item 7).

OCR confusions (O/0, I/1, S/5, B/8, Z/2) that break a format rule get a
proposals list: candidate substitutions are enumerated and tested against
the declared format rules. Exactly one candidate passes → propose it with
needs_review. Zero or several pass → flag, never guess.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

# Case-insensitive OCR-confusable mapping: original character -> alternatives.
CONFUSABLE_ALTERNATIVES: dict[str, tuple[str, ...]] = {
    "0": ("O", "D"),
    "O": ("0",),
    "1": ("I", "L"),
    "I": ("1",),
    "L": ("1",),
    "5": ("S",),
    "S": ("5",),
    "8": ("B",),
    "B": ("8",),
    "2": ("Z",),
    "Z": ("2",),
    "6": ("G",),
    "G": ("6",),
}

# Cap the enumeration: beyond this many confusable positions we do not
# enumerate candidates; the text is flagged as ambiguous outright.
_MAX_POSITIONS = 5
_MAX_CANDIDATES = 32


@dataclass(frozen=True)
class AmbiguityOutcome:
    text: str
    status: str  # "clean" | "proposed" | "ambiguous"
    proposals: tuple[str, ...] = ()  # exactly one when status == "proposed"
    reason: str = ""


def confusable_positions(text: str) -> list[int]:
    return [i for i, ch in enumerate(text) if ch in CONFUSABLE_ALTERNATIVES]


def generate_candidates(text: str) -> list[str]:
    """All single- and multi-position confusable substitutions, capped."""
    positions = confusable_positions(text)
    if not positions or len(positions) > _MAX_POSITIONS:
        return []
    candidates: list[str] = []
    for count in range(1, len(positions) + 1):
        for combo in itertools.combinations(positions, count):
            options = [CONFUSABLE_ALTERNATIVES[text[i]] for i in combo]
            for replacement in itertools.product(*options):
                chars = list(text)
                for i, rep in zip(combo, replacement, strict=True):
                    chars[i] = rep
                candidate = "".join(chars)
                if candidate not in candidates:
                    candidates.append(candidate)
            if len(candidates) > _MAX_CANDIDATES:
                return candidates[:_MAX_CANDIDATES]
    return candidates


def resolve_ambiguity(
    text: str,
    format_rules: list[str],
    *,
    extra_validators: list | None = None,
) -> AmbiguityOutcome:
    """Test the reading and its confusable candidates against format rules.

    ``format_rules`` are regex patterns (fullmatch) the value must satisfy;
    ``extra_validators`` are callables str -> bool (e.g. a range check).
    Returns an AmbiguityOutcome; a proposal is only made when exactly one
    candidate (or the original text) passes.
    """
    validators = list(extra_validators or [])

    def passes(value: str) -> bool:
        for pattern in format_rules:
            if re.fullmatch(pattern, value) is None:
                return False
        return all(v(value) for v in validators)

    if passes(text):
        return AmbiguityOutcome(text, "clean")
    candidates = generate_candidates(text)
    if not candidates:
        return AmbiguityOutcome(
            text, "ambiguous", reason="no format rule matches and no viable confusable candidates"
        )
    good = [c for c in candidates if passes(c)]
    if len(good) == 1:
        return AmbiguityOutcome(
            text,
            "proposed",
            proposals=(good[0],),
            reason="unique candidate matches the format rules",
        )
    return AmbiguityOutcome(
        text,
        "ambiguous",
        proposals=tuple(good),
        reason=f"{len(good)} candidates match the format rules; cannot choose",
    )
