"""Code-based relevance and freshness of a search result (used by score.py).

relevant = the result (title + snippet + URL) mentions the query's place AND its topic,
using the keywords in relevance.json. fresh / old / undated = published within
`fresh_months` of the run, earlier, or no date we can parse.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

BASE_DIR = Path(__file__).resolve().parent

_DIACRITICS = re.compile("[ً-ْٰـ]")  # harakat, superscript alef, tatweel
_ARABIC = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_MARKS = re.compile("[‎‏؜‪-‮]")  # RTL/LTR marks Google adds


def normalize_text(text: str) -> str:
    """Lowercase; Arabic: أ/إ/آ -> ا, ة -> ه, ى -> ي, no diacritics."""
    return _DIACRITICS.sub("", text.lower().translate(_ARABIC))


# --- dates ---------------------------------------------------------------------------------

_UNITS = {
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
}
# Arabic units after normalize_text (ة -> ه, أ -> ا); the dual form means 2.
_AR_UNITS = {
    "دقيقه": "minute", "دقائق": "minute", "دقيقتين": "minute",
    "ساعه": "hour", "ساعات": "hour", "ساعتين": "hour",
    "يوم": "day", "ايام": "day", "يومين": "day",
    "اسبوع": "week", "اسابيع": "week", "اسبوعين": "week",
    "شهر": "month", "اشهر": "month", "شهور": "month", "شهرين": "month",
    "سنه": "year", "سنوات": "year", "سنتين": "year", "عام": "year", "اعوام": "year",
}  # fmt: skip
_EN_AGO = re.compile(r"(\d+)\s*(minute|hour|day|week|month|year)s?\s+ago")
_AR_AGO = re.compile(r"(?:قبل|منذ)\s*(\d+)?\s*(" + "|".join(_AR_UNITS) + ")")
_DMY = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_TEXT_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d")


def parse_date(text: str | None, now: datetime) -> datetime | None:
    """Tavily and Serper date text -> datetime (UTC), or None if missing or unknown.
    Handles "Mar 3, 2026", "11/11/2026" (day/month/year, Arabic digits and RTL marks
    allowed), "3 days ago", "قبل ٣ أيام", ISO and RFC 2822 dates."""
    if not text:
        return None
    clean = normalize_text(_MARKS.sub("", text.translate(_DIGITS))).strip()
    if m := _EN_AGO.search(clean):
        return now - int(m.group(1)) * _UNITS[m.group(2)]
    if m := _AR_AGO.search(clean):
        unit = _AR_UNITS[m.group(2)]
        count = int(m.group(1)) if m.group(1) else (2 if m.group(2).endswith("ين") else 1)
        return now - count * _UNITS[unit]
    if m := _DMY.search(clean):
        day, month, year = (int(g) for g in m.groups())
        try:
            return datetime(year, month, day, tzinfo=UTC)
        except ValueError:
            return None
    for parse in (
        lambda s: datetime.fromisoformat(s.replace("z", "+00:00")),
        parsedate_to_datetime,
        *[(lambda s, f=f: datetime.strptime(s.title(), f)) for f in _TEXT_FORMATS],
    ):
        try:
            parsed = parse(clean)
        except (ValueError, TypeError, IndexError):
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _months_before(when: datetime, months: int) -> datetime:
    year, month = divmod(when.year * 12 + when.month - 1 - months, 12)
    day = min(when.day, 28)
    return when.replace(year=year, month=month + 1, day=day)


# --- relevance -----------------------------------------------------------------------------


@dataclass
class Relevance:
    place: dict[str, list[str]]  # site -> keywords (normalised)
    topic: dict[str, list[str]]  # query group -> keywords (normalised)
    fresh_months: int = 24

    def is_relevant(self, result: dict[str, Any], site: str, group: str) -> bool:
        """Place AND topic keyword in title + snippet + URL (URL slugs: - and _ as spaces)."""
        text = normalize_text(
            " ".join(
                (
                    result.get("title") or "",
                    result.get("snippet") or "",
                    unquote(result.get("url") or "").replace("-", " ").replace("_", " "),
                )
            )
        )
        place = any(k in text for k in self.place.get(site, []))
        return place and any(k in text for k in self.topic.get(group, []))

    def freshness(self, date_text: str | None, run_timestamp: str) -> str:
        """ "fresh", "old" or "undated"."""
        now = datetime.fromisoformat(run_timestamp)
        published = parse_date(date_text, now)
        if published is None:
            return "undated"
        return "fresh" if published >= _months_before(now, self.fresh_months) else "old"


def load_relevance(base_dir: Path = BASE_DIR) -> Relevance | None:
    path = base_dir / "relevance.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    norm = lambda d: {k: [normalize_text(w) for w in v] for k, v in d.items()}  # noqa: E731
    return Relevance(norm(data["place"]), norm(data["topic"]), data.get("fresh_months", 24))
