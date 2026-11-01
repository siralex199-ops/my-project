"""دسترسی به داده‌های بازی‌ها، تیم‌ها و لیگ‌ها."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Match:
    league: str
    season: str
    date: date
    home: str
    away: str
    home_goals: int | None
    away_goals: int | None

    @property
    def played(self) -> bool:
        return self.home_goals is not None and self.away_goals is not None


def _parse_date(raw: str) -> date | None:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


@lru_cache(maxsize=1)
def load_matches() -> tuple[Match, ...]:
    """بارگذاری تمام بازی‌ها از data/matches.csv."""
    path = DATA_DIR / "matches.csv"
    if not path.exists():
        raise FileNotFoundError(
            "فایل داده پیدا نشد. ابتدا دستور `python3 scripts/build_dataset.py` را اجرا کنید."
        )
    matches: list[Match] = []
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            day = _parse_date(row["date"])
            if day is None:
                continue
            hg = int(row["hg"]) if row["hg"] != "" else None
            ag = int(row["ag"]) if row["ag"] != "" else None
            matches.append(
                Match(
                    league=row["league"],
                    season=row["season"],
                    date=day,
                    home=row["home"],
                    away=row["away"],
                    home_goals=hg,
                    away_goals=ag,
                )
            )
    matches.sort(key=lambda m: (m.date, m.league))
    return tuple(matches)


@lru_cache(maxsize=1)
def load_teams() -> dict[str, dict]:
    path = DATA_DIR / "teams.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_leagues() -> dict[str, dict]:
    path = DATA_DIR / "leagues.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def matches_by_league() -> dict[str, list[Match]]:
    grouped: dict[str, list[Match]] = {}
    for match in load_matches():
        grouped.setdefault(match.league, []).append(match)
    return grouped


def team_name(key: str, lang: str = "fa") -> str:
    info = load_teams().get(key)
    if not info:
        return key
    return info.get(lang) or info.get("en") or key


def resolve_team(query: str, league: str | None = None) -> str:
    """تبدیل نام تیم (فارسی، انگلیسی یا کلید) به کلید یکتا."""
    import difflib

    teams = load_teams()
    q = query.strip().lower()
    candidates = {
        key: info
        for key, info in teams.items()
        if league is None or league in info.get("leagues", [])
    }
    if not candidates:
        candidates = teams

    if q in candidates:
        return q
    for key, info in candidates.items():
        if q in {str(info.get("en", "")).lower(), str(info.get("fa", "")).lower()}:
            return key
    # جست‌وجوی تقریبی
    pool: dict[str, str] = {}
    for key, info in candidates.items():
        pool[key] = key
        pool[str(info.get("en", "")).lower()] = key
        pool[str(info.get("fa", ""))] = key
    close = difflib.get_close_matches(q, list(pool), n=1, cutoff=0.6)
    if close:
        return pool[close[0]]
    close = difflib.get_close_matches(query.strip(), list(pool), n=1, cutoff=0.6)
    if close:
        return pool[close[0]]
    raise KeyError(f"تیم «{query}» پیدا نشد")


def current_season(matches: list[Match]) -> str:
    return max(matches, key=lambda m: (m.season, m.date)).season
