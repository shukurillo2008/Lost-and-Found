"""Heuristic scoring engine for candidate lost/found matches.

Single source of truth for every matching weight (course §4.3): the numbers
below are the ONLY definition used by the worker, the staff review pages and
the bot, so changing a weight here re-scores the whole system consistently.

How a pair is scored
--------------------
* the category must be identical, otherwise the pair scores 0;
* same color: +3
* item found at or after the lost date, within 14 days: +2
* same building: +2, and +1 more for the same area
* words shared between the two title+description texts (lower-cased, stop
  words removed): +1 per shared word, capped at +4
* the worker auto-suggests only pairs scoring strictly above 5
  (``MIN_SYSTEM_SCORE``).

``score_breakdown(lost, item)`` returns one numeric entry per criterion plus
diagnostic fields; ``match_score`` sums the numeric entries only. The whole
breakdown is stored verbatim in ``MatchSuggestion.score_breakdown`` so staff
can see exactly why a pair scored what it scored.

Input contract: ``item`` may be a ``StoredItem`` or a ``FoundReport`` (kept by
the finder). Both must be saved instances; for ``StoredItem`` callers should
prefetch ``found_report`` (``select_related``) in list contexts.
"""
from __future__ import annotations

import re

from django.utils import timezone

from reports.models import FoundReport

# ---------------------------------------------------------------------------
# Weights — the ONLY place they are defined. Rationale: category identity is
# mandatory (a lost wallet is never a jacket); color and time are the two
# most user-visible cues, shared words catch free-text descriptions, and the
# area bonus exists because students lose things right where they stand.
# ---------------------------------------------------------------------------
WEIGHT_COLOR = 3
WEIGHT_TEMPORAL = 2
TEMPORAL_WINDOW_DAYS = 14
WEIGHT_SAME_BUILDING = 2
WEIGHT_SAME_AREA_EXTRA = 1
WEIGHT_PER_SHARED_WORD = 1
WEIGHT_WORD_CAP = 4

MIN_SYSTEM_SCORE = 5  # worker auto-suggests when score > MIN_SYSTEM_SCORE

# Keys of ``score_breakdown`` that carry points (summed by ``match_score``).
# Everything else in the breakdown is diagnostic and is never summed.
SCORE_KEYS = ("color", "temporal", "building", "area", "words")

MIN_TOKEN_LEN = 3

STOP_WORDS = frozenset(
    """
    # English function words
    a an the and or of in on at to for with from by is are was were be been
    being it its this that these those i me my mine we our ours you your
    yours he she they them their as but if not no yes very has have had do
    does did just out up off about into over under
    # Uzbek (Latin) function words; apostrophes are stripped, so
    # yo'q -> yoq, o'sha -> osha, o'z -> oz
    va yoki bilan uchun bor yoq edi emas kerak kabi ham yana eng juda men
    mening meniki bu shu osha ana bir biror kim nima qachon qayerda bugun
    kecha ertaga lekin ammo keyin oldin boshqa har hech hamma oz
    # Russian function words
    и в на с к у о об не да нет я мне меня мой моя моё мое мои был была
    было были для от до или это эта этот эти там тут как что же бы очень
    при по за из
    """.split()
)

_TOKEN_RE = re.compile(r"[^\w]+", flags=re.UNICODE)
_APOSTROPHES = str.maketrans("", "", "ʻʼ‘’'`")


def tokenize(text: str) -> set[str]:
    """Lower-case, split on non-word characters, drop stop words + short tokens.

    Apostrophe variants (typographic and ASCII) are stripped first so that
    Uzbek "yo'q" and "yoq" collapse to one token on both sides.
    """
    if not text:
        return set()
    tokens: set[str] = set()
    for raw in _TOKEN_RE.split(text.lower().translate(_APOSTROPHES)):
        if len(raw) >= MIN_TOKEN_LEN and raw not in STOP_WORDS:
            tokens.add(raw)
    return tokens


def _item_side(item):
    """Extract the fact tuple the scoring needs from either side object.

    A ``StoredItem`` without a linked ``FoundReport`` (a walk-in) uses its
    received date as the "found" date and has no location.
    """
    if isinstance(item, FoundReport):
        linked_report, received_fallback = item, None
    else:  # storage.StoredItem
        linked_report, received_fallback = item.found_report, item.received_at

    if linked_report is not None:
        found_date = linked_report.date_found
        location = linked_report.location
    else:
        found_date = timezone.localdate(received_fallback) if received_fallback else None
        location = None

    return {
        "category_id": item.category_id,
        "color_id": item.color_id,
        "title": item.title,
        "description": item.description,
        "found_date": found_date,
        "location": location,
    }


def score_breakdown(lost, item) -> dict:
    """Score one lost report against one item side; return the full breakdown."""
    side = _item_side(item)
    breakdown: dict = {"category_match": lost.category_id == side["category_id"]}

    if not breakdown["category_match"]:
        # Category identity is required; no other criterion is even considered.
        return breakdown

    lost_loc, item_loc = lost.location, side["location"]
    lost_day, found_day = lost.date_lost, side["found_date"]

    # Temporal: the item must be found at/after the loss, within the window.
    if (
        lost_day
        and found_day
        and lost_day <= found_day
        and (found_day - lost_day).days <= TEMPORAL_WINDOW_DAYS
    ):
        breakdown["temporal"] = WEIGHT_TEMPORAL

    # Color: both sides must know their color.
    if lost.color_id and side["color_id"] and lost.color_id == side["color_id"]:
        breakdown["color"] = WEIGHT_COLOR

    # Location: building by its canonical (uz) name; area bonus needs the
    # same Location row, since a row IS one building+area pair.
    if lost_loc is not None and item_loc is not None:
        if lost_loc.pk == item_loc.pk:
            breakdown["building"] = WEIGHT_SAME_BUILDING
            breakdown["area"] = WEIGHT_SAME_AREA_EXTRA
        elif lost_loc.building_uz == item_loc.building_uz:
            breakdown["building"] = WEIGHT_SAME_BUILDING

    # Word overlap over title+description, shared words, capped.
    shared = sorted(tokenize(f"{lost.title} {lost.description}") & tokenize(f"{side['title']} {side['description']}"))
    if shared:
        breakdown["words"] = min(len(shared) * WEIGHT_PER_SHARED_WORD, WEIGHT_WORD_CAP)

    # Diagnostics — never summed, but stored for the review UI.
    breakdown.update(
        {
            "shared_words": shared,
            "lost_date": lost_day.isoformat() if lost_day else None,
            "found_date": found_day.isoformat() if found_day else None,
        }
    )
    return breakdown


def score_from_breakdown(breakdown: dict) -> int:
    """Total of the scored keys in an already-built breakdown.

    Lets callers that staged the breakdown (the bot's ``this-is-mine``
    creator, the worker) score once and never re-compute.
    """
    return sum(breakdown.get(key, 0) for key in SCORE_KEYS)


def match_score(lost, item) -> int:
    """Integer score = total of the scored keys in the breakdown."""
    return score_from_breakdown(score_breakdown(lost, item))


def strong_enough(score: int) -> bool:
    """Worker rule: auto-suggest only when the score is strictly above the threshold."""
    return score > MIN_SYSTEM_SCORE
