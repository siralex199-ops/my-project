"""لایه‌ی سطح‌بالا: بارگذاری لیگ، برازش مدل، پیش‌بینی بازی‌ها و شبیه‌سازی فصل."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

from .dataset import (
    Match,
    load_leagues,
    load_matches,
    load_teams,
    matches_by_league,
    team_name,
)
from .model import DixonColes, Prediction

DEFAULT_AS_OF = date.today()
TITLE_SPOTS = {"en.1": 1, "en.2": 2, "es.1": 1, "it.1": 1, "de.1": 1, "fr.1": 1, "nl.1": 1, "pt.1": 1}


@dataclass
class FixturePrediction:
    match: Match
    prediction: Prediction

    def as_dict(self) -> dict:
        return {
            "league": self.match.league,
            "season": self.match.season,
            "date": self.match.date.isoformat(),
            "home": self.match.home,
            "away": self.match.away,
            "home_fa": team_name(self.match.home),
            "away_fa": team_name(self.match.away),
            **self.prediction.as_dict(),
        }


def _played(matches: list[Match]) -> list[Match]:
    return [m for m in matches if m.played]


class LeaguePredictor:
    """مدلِ آماده‌به‌استفاده برای یک لیگ."""

    def __init__(
        self,
        league: str,
        as_of: date | None = None,
        history_years: int = 5,
        model: DixonColes | None = None,
    ) -> None:
        if league not in load_leagues():
            raise KeyError(f"لیگ ناشناخته: {league}")
        self.league = league
        self.as_of = as_of or DEFAULT_AS_OF
        self.history_years = history_years
        self.matches = sorted(matches_by_league().get(league, []), key=lambda m: m.date)
        start = date(self.as_of.year - history_years, 7, 1)
        train = [m for m in self.matches if m.played and start <= m.date <= self.as_of]
        if len(train) < 50:  # برای لیگ‌های کم‌بازی، همه‌ی تاریخچه
            train = [m for m in self.matches if m.played]
        self.model = model or DixonColes(half_life_days=365, ridge=0.02, iterations=350).fit(
            train, as_of=self.as_of
        )
        self.season = self._current_season()

    # ------------------------------------------------------------- basics
    def _current_season(self) -> str:
        played = [m for m in _played(self.matches) if m.date <= self.as_of]
        if played:
            return max(played, key=lambda m: m.date).season
        if self.matches:
            return self.matches[-1].season
        return ""

    def season_matches(self, season: str | None = None) -> list[Match]:
        season = season or self.season
        return [m for m in self.matches if m.season == season]

    def teams(self) -> list[str]:
        """تیم‌های حاضر در فصل جاری."""
        current = self.season_matches()
        keys = {m.home for m in current} | {m.away for m in current}
        if not keys:
            keys = set(self.model.teams)
        return sorted(keys, key=lambda k: -self.model.rating(k).power)

    def predict(self, home: str, away: str) -> Prediction:
        for team in (home, away):
            if team not in self.model.attack:
                self.model.attack.setdefault(team, 0.0)
                self.model.defence.setdefault(team, 0.0)
        return self.model.predict(home, away)

    # ----------------------------------------------------------- fixtures
    @property
    def last_played_date(self) -> date | None:
        played = [m for m in _played(self.matches) if m.date <= self.as_of]
        return max((m.date for m in played), default=None)

    def upcoming(self, season: str | None = None) -> list[Match]:
        """بازی‌های بدون نتیجه در فصل جاری، از تاریخ آخرین نتیجه‌ی ثبت‌شده به بعد.

        بازی‌های فصل‌های قدیم که هیچ‌وقت نتیجه‌شان ثبت نشده «پیش‌رو» نیستند و
        همچنین بازی‌های ابتدای فصل که نتیجه‌شان در داده جا افتاده حذف می‌شوند.
        """
        season = season or self.season
        cutoff = self.last_played_date
        candidates = [
            m
            for m in self.matches
            if not m.played and (season is None or m.season == season)
        ]
        if cutoff is not None:
            candidates = [m for m in candidates if m.date >= cutoff]
        return sorted(candidates, key=lambda m: (m.date, m.home))

    def fixtures(self, limit: int = 40, nights: int | None = None, fresh_only: bool = False) -> list[FixturePrediction]:
        """بازی‌های پیش‌رو (بدون نتیجه) به‌ترتیب تاریخ."""
        upcoming = self.upcoming()
        if fresh_only:
            upcoming = [m for m in upcoming if m.date >= self.as_of]
        if not upcoming:
            return []
        if nights is not None:
            horizon = upcoming[0].date + timedelta(days=nights)
            upcoming = [m for m in upcoming if m.date <= horizon]
        return [FixturePrediction(m, self.predict(m.home, m.away)) for m in upcoming[:limit]]

    def recent_results(self, limit: int = 10) -> list[dict]:
        played = sorted(_played(self.matches), key=lambda m: (m.date, m.home), reverse=True)
        out = []
        for m in played[:limit]:
            out.append(
                {
                    "date": m.date.isoformat(),
                    "home": m.home,
                    "away": m.away,
                    "home_fa": team_name(m.home),
                    "away_fa": team_name(m.away),
                    "home_goals": m.home_goals,
                    "away_goals": m.away_goals,
                }
            )
        return out

    # -------------------------------------------------------------- table
    def standings(self, season: str | None = None) -> list[dict]:
        rows: dict[str, dict] = {}
        for m in self.season_matches(season):
            if not m.played:
                continue
            for team, gf, ga in ((m.home, m.home_goals, m.away_goals), (m.away, m.away_goals, m.home_goals)):
                row = rows.setdefault(
                    team,
                    {"team": team, "name": team_name(team), "played": 0, "won": 0, "drawn": 0,
                     "lost": 0, "gf": 0, "ga": 0, "points": 0},
                )
                row["played"] += 1
                row["gf"] += gf
                row["ga"] += ga
                if gf > ga:
                    row["won"] += 1
                    row["points"] += 3
                elif gf == ga:
                    row["drawn"] += 1
                    row["points"] += 1
                else:
                    row["lost"] += 1
        table = sorted(rows.values(), key=lambda r: (-r["points"], -(r["gf"] - r["ga"]), -r["gf"]))
        for i, row in enumerate(table, 1):
            row["position"] = i
            row["gd"] = row["gf"] - row["ga"]
        return table

    # -------------------------------------------------------------- power
    def power_table(self) -> list[dict]:
        rows = []
        for team in self.teams():
            r = self.model.rating(team)
            rows.append(
                {
                    "team": team,
                    "name": team_name(team),
                    "attack": r.attack,
                    "defence": r.defence,
                    "power": r.power,
                    "matches": round(r.matches, 1),
                }
            )
        rows.sort(key=lambda r: -r["power"])
        for i, row in enumerate(rows, 1):
            row["rank"] = i
        return rows

    # --------------------------------------------------------- simulation
    def simulate(self, runs: int = 1500, seed: int = 7) -> list[dict]:
        """شبیه‌سازی مونت‌کارلوی ادامه‌ی فصل (Array of final tables)."""
        played = [m for m in self.season_matches() if m.played]
        remaining = [m for m in self.season_matches() if not m.played]
        base = {row["team"]: row["points"] for row in self.standings()}
        teams = list(base)
        if not teams:
            return []
        events = []
        for m in remaining:
            lam, mu = self.model.goal_rates(m.home, m.away)
            events.append((m.home, m.away, self._poisson_sampler(lam), self._poisson_sampler(mu)))

        rng = random.Random(seed)
        n = len(teams)
        idx = {t: i for i, t in enumerate(teams)}
        titles = [0] * n
        top = [0] * n
        bottom = [0] * n
        total_points = [0] * n

        for _ in range(runs):
            pts = list(base[t] for t in teams)
            gd = [0] * n
            for home, away, ps_home, ps_away in events:
                hg = ps_home(rng)
                ag = ps_away(rng)
                i, j = idx[home], idx[away]
                gd[i] += hg - ag
                gd[j] += ag - hg
                if hg > ag:
                    pts[i] += 3
                elif hg < ag:
                    pts[j] += 3
                else:
                    pts[i] += 1
                    pts[j] += 1
            order = sorted(range(n), key=lambda k: (-pts[k], -gd[k]))
            titles[order[0]] += 1
            for k in order[:5]:
                top[k] += 1
            for k in order[-3:]:
                bottom[k] += 1
            for k in range(n):
                total_points[k] += pts[k]

        result = []
        for k, team in enumerate(teams):
            result.append(
                {
                    "team": team,
                    "name": team_name(team),
                    "current_points": base[team],
                    "title_prob": titles[k] / runs,
                    "top5_prob": top[k] / runs,
                    "relegation_prob": bottom[k] / runs,
                    "exp_points": total_points[k] / runs,
                }
            )
        result.sort(key=lambda r: (-r["title_prob"], -r["exp_points"]))
        for i, row in enumerate(result, 1):
            row["projected_rank"] = i
        return result

    @staticmethod
    def _poisson_sampler(lam: float):
        if lam <= 0:
            return lambda rng: 0
        limit = math.exp(-lam)

        def sample(rng: random.Random) -> int:
            k = 0
            p = 1.0
            while True:
                k += 1
                p *= rng.random()
                if p <= limit:
                    return k - 1
                if k > 18:
                    return k - 1

        return sample


class PredictorRegistry:
    """کش مدل‌های هر لیگ تا از برازش تکراری جلوگیری شود."""

    def __init__(self, as_of: date | None = None) -> None:
        self.as_of = as_of or DEFAULT_AS_OF
        self._cache: dict[str, LeaguePredictor] = {}
        self._sim_cache: dict[str, list[dict]] = {}

    def get(self, league: str) -> LeaguePredictor:
        if league not in self._cache:
            self._cache[league] = LeaguePredictor(league, as_of=self.as_of)
        return self._cache[league]

    def leagues(self) -> list[dict]:
        """فهرست لیگ‌ها (بدون نیاز به برازش مدل)."""
        meta = load_leagues()
        grouped = matches_by_league()
        out = []
        for key, info in meta.items():
            matches = grouped.get(key, [])
            played = [m for m in _played(matches) if m.date <= self.as_of]
            season = max(played, key=lambda m: m.date).season if played else (matches[-1].season if matches else "")
            current = [m for m in matches if m.season == season]
            out.append(
                {
                    "id": key,
                    "name_fa": info.get("name_fa", key),
                    "name_en": info.get("name_en", key),
                    "country": info.get("country", ""),
                    "flag": info.get("flag", "⚽"),
                    "season": season,
                    "teams": len({m.home for m in current} | {m.away for m in current}),
                    "fixtures": len([m for m in current if not m.played and (not played or m.date >= played[-1].date)]),
                    "played": len(played),
                    "last_result": played[-1].date.isoformat() if played else None,
                }
            )
        return out

    def simulate(self, league: str, runs: int = 1500) -> list[dict]:
        if league not in self._sim_cache:
            self._sim_cache[league] = self.get(league).simulate(runs=runs)
        return self._sim_cache[league]
