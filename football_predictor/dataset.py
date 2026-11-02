"""دسترسی به داده‌های بازی‌ها، تیم‌ها و لیگ‌ها."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# نتایج دستی که کاربر ثبت می‌کند؛ بعد از هر بازسازی دیتاست هم حفظ می‌شود
MANUAL_RESULTS = DATA_DIR / "manual_results.csv"

# جدول‌های رسمی واردشده (مثلاً از varzesh3) — جدا از جدول محاسبه‌شده از نتایج
OFFICIAL_STANDINGS = DATA_DIR / "standings_official.json"


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
    matches = _apply_manual_results(matches)
    matches.sort(key=lambda m: (m.date, m.league))
    return tuple(matches)


def _apply_manual_results(matches: list[Match]) -> list[Match]:
    """اعمال نتایجی که به‌صورت دستی در data/manual_results.csv ثبت شده‌اند.

    اگر بازی از قبل در دیتاست باشد، نتیجه‌اش جایگزین می‌شود؛ در غیر این صورت
    به‌عنوان یک بازی جدید اضافه می‌شود.
    """
    if not MANUAL_RESULTS.exists():
        return matches
    index = {(m.league, m.home, m.away, m.date): i for i, m in enumerate(matches)}
    with MANUAL_RESULTS.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if not row.get("league") or not row.get("home") or not row.get("away"):
                continue
            day = _parse_date(row["date"])
            if day is None:
                continue
            hg = int(row["hg"]) if row.get("hg", "") != "" else None
            ag = int(row["ag"]) if row.get("ag", "") != "" else None
            if hg is None or ag is None:
                continue
            key = (row["league"], row["home"], row["away"], day)
            entry = Match(
                league=row["league"],
                season=row.get("season") or "manual",
                date=day,
                home=row["home"],
                away=row["away"],
                home_goals=hg,
                away_goals=ag,
            )
            if key in index:
                matches[index[key]] = entry
            else:
                index[key] = len(matches)
                matches.append(entry)
    return matches


@lru_cache(maxsize=1)
def load_teams() -> dict[str, dict]:
    path = DATA_DIR / "teams.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_official_standings() -> dict:
    """جدول‌های رسمی واردشده: {league: {source, updated_at, rows}}."""
    if not OFFICIAL_STANDINGS.exists():
        return {}
    try:
        payload = json.loads(OFFICIAL_STANDINGS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload.get("leagues", {})


def official_leagues() -> list[dict]:
    """لیگ‌هایی که جدول رسمی دارند (شامل لیگ‌هایی که در دیتاست مدل نیستند)."""
    official = load_official_standings() or {}
    model = load_leagues()
    out = []
    for key, block in official.items():
        info = model.get(key, {})
        title = block.get("title") or info.get("name_fa") or key
        out.append(
            {
                "id": key,
                "name_fa": info.get("name_fa") or title,
                "name_en": info.get("name_en") or title,
                "country": info.get("country", ""),
                "flag": info.get("flag", "⚽"),
                "season": "",
                "teams": len(block.get("rows") or []),
                "official_only": key not in model,
                "official_updated_at": block.get("updated_at", ""),
                "official_source": block.get("source", ""),
            }
        )
    return out


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
