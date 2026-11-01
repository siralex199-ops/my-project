"""تست‌های مدل و لایه داده — اجرا: python3 -m unittest discover -s tests"""

from __future__ import annotations

import math
import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from football_predictor.dataset import Match, load_matches, load_teams, resolve_team  # noqa: E402
from football_predictor.model import DixonColes, poisson_pmf, tau  # noqa: E402
from football_predictor.predictor import LeaguePredictor  # noqa: E402


def synthetic_league(seed: int = 3, matches_per_pair: int = 6):
    """لیگ مصنوعی با تیم‌های قوی/ضعیف برای آزمون برازش."""
    rng = random.Random(seed)
    teams = ["قوی", "متوسط", "ضعیف"]
    strength = {"قوی": (0.65, -0.45), "متوسط": (0.0, 0.0), "ضعیف": (-0.55, 0.5)}
    rows = []
    start = date(2024, 8, 1)
    i = 0
    for home in teams:
        for away in teams:
            if home == away:
                continue
            for k in range(matches_per_pair):
                ah, dh = strength[home]
                aa, da = strength[away]
                lam = math.exp(ah + da + 0.25)
                mu = math.exp(aa + dh)
                hg = _sample_poisson(rng, lam)
                ag = _sample_poisson(rng, mu)
                rows.append(
                    Match(
                        league="test",
                        season="2024-25",
                        date=start + timedelta(days=3 * i),
                        home=home,
                        away=away,
                        home_goals=hg,
                        away_goals=ag,
                    )
                )
                i += 1
    return rows


def _sample_poisson(rng: random.Random, lam: float) -> int:
    limit = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= limit:
            return k - 1


class TestMathPrimitives(unittest.TestCase):
    def test_poisson_sums_to_one(self):
        for lam in (0.4, 1.0, 2.7):
            total = sum(poisson_pmf(k, lam) for k in range(40))
            self.assertAlmostEqual(total, 1.0, places=9)

    def test_tau_defaults_to_one_outside_low_scores(self):
        self.assertEqual(tau(3, 2, 1.5, 1.1, -0.05), 1.0)

    def test_tau_low_scores(self):
        lam, mu, rho = 1.5, 1.1, -0.06
        self.assertAlmostEqual(tau(0, 0, lam, mu, rho), 1 - lam * mu * rho)
        self.assertAlmostEqual(tau(0, 1, lam, mu, rho), 1 + lam * rho)
        self.assertAlmostEqual(tau(1, 0, lam, mu, rho), 1 + mu * rho)
        self.assertAlmostEqual(tau(1, 1, lam, mu, rho), 1 - rho)


class TestDixonColes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matches = synthetic_league()
        cls.model = DixonColes(iterations=400).fit(cls.matches, as_of=date(2025, 6, 1))

    def test_learns_team_strength(self):
        self.assertGreater(self.model.rating("قوی").power, self.model.rating("متوسط").power)
        self.assertGreater(self.model.rating("متوسط").power, self.model.rating("ضعیف").power)

    def test_home_advantage_positive(self):
        self.assertGreater(self.model.home_adv, 0.0)

    def test_probabilities_are_normalized(self):
        p = self.model.predict("قوی", "ضعیف")
        self.assertAlmostEqual(p.prob_home + p.prob_draw + p.prob_away, 1.0, places=6)
        self.assertGreater(p.prob_home, p.prob_away)
        self.assertAlmostEqual(sum(sum(row) for row in p.matrix), 1.0, places=6)

    def test_markets_consistent(self):
        p = self.model.predict("متوسط", "قوی")
        self.assertAlmostEqual(p.over_under["over_1_5"] + (1 - p.over_under["over_1_5"]), 1.0, places=9)
        self.assertGreater(p.over_under["over_1_5"], p.over_under["over_2_5"])
        self.assertGreater(p.over_under["over_2_5"], p.over_under["over_3_5"])
        self.assertTrue(0 < p.btts < 1)
        self.assertGreaterEqual(p.scores[0][2], p.scores[1][2])

    def test_unknown_team_is_average(self):
        p = self.model.predict("قوی", "تیم ناشناخته")
        self.assertGreater(p.prob_home, 0.4)


class TestDataset(unittest.TestCase):
    def test_matches_loaded(self):
        matches = load_matches()
        self.assertGreater(len(matches), 10_000)
        self.assertTrue(all(m.date and m.league for m in matches))

    def test_teams_have_persian_names(self):
        teams = load_teams()
        self.assertIn("arsenal", teams)
        self.assertEqual(teams["arsenal"]["fa"], "آرسنال")

    def test_resolve_team_by_persian_and_english(self):
        self.assertEqual(resolve_team("آرسنال", "en.1"), "arsenal")
        self.assertEqual(resolve_team("Arsenal", "en.1"), "arsenal")
        self.assertEqual(resolve_team("آرسنال"), "arsenal")


class TestPredictor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.predictor = LeaguePredictor("en.1", as_of=date(2026, 11, 1))

    def test_season_detected(self):
        self.assertEqual(self.predictor.season, "2026-27")

    def test_fixtures_have_predictions(self):
        fixtures = self.predictor.fixtures(limit=5)
        self.assertTrue(fixtures)
        for fixture in fixtures:
            self.assertAlmostEqual(
                fixture.prediction.prob_home
                + fixture.prediction.prob_draw
                + fixture.prediction.prob_away,
                1.0,
                places=6,
            )

    def test_standings_sorted(self):
        table = self.predictor.standings()
        self.assertEqual(len(table), 20)
        points = [row["points"] for row in table]
        self.assertEqual(points, sorted(points, reverse=True))

    def test_simulation_probabilities(self):
        rows = self.predictor.simulate(runs=120)
        self.assertEqual(len(rows), 20)
        self.assertAlmostEqual(sum(r["title_prob"] for r in rows), 1.0, places=6)
        self.assertAlmostEqual(sum(r["relegation_prob"] for r in rows), 3.0, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
