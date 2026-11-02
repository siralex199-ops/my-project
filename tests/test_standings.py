"""تست ورود و خواندن جدول‌های رسمی (منبع: ورزش۳)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from football_predictor.dataset import load_official_standings, load_teams  # noqa: E402
from football_predictor.predictor import LeaguePredictor  # noqa: E402

spec = importlib.util.spec_from_file_location("import_standings", ROOT / "scripts" / "import_standings.py")
import_standings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(import_standings)

SAMPLE = """
| # |  | تیم | بازی | برد | مساوی | باخت | گل -/+ | تفاضل  | امتیاز | بازی‌های اخیر |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 |  | آرسنال | 9 | 8 | 0 | 1 | 14-5 | 9 | 24 | L W W W W |
| 12 |  | نیوکسل | 8 | 3 | 2 | 3 | 12-14 | -2 | 11 | L W L L W |
| 16 |  | کاونتری | 9 | 3 | 0 | 6 | 9-16 | -7 | 9 | W W L L W |
"""


class TestParser(unittest.TestCase):
    def test_parse_goals_separately_from_numbers(self):
        rows = import_standings.parse_rows(SAMPLE)
        records = [import_standings.row_to_record(r) for r in rows]
        records = [r for r in records if r]
        self.assertEqual(len(records), 3)
        arsenal = next(r for r in records if r["name"] == "آرسنال")
        self.assertEqual(arsenal["played"], 9)
        self.assertEqual(arsenal["won"], 8)
        self.assertEqual((arsenal["gf"], arsenal["ga"]), (14, 5))
        self.assertEqual(arsenal["points"], 24)

    def test_row_with_inconsistent_totals_is_rejected(self):
        broken = ["5", "", "تیم تست", "9", "5", "0", "1", "10-5", "5", "15", "W"]
        self.assertIsNone(import_standings.row_to_record(broken))

    def test_team_resolution_by_fa_name(self):
        teams = load_teams()
        self.assertEqual(import_standings.resolve("نیوکسل", "en.1", teams, {}), "newcastle")
        self.assertEqual(import_standings.resolve("کاونتری", "en.1", teams, {}), "coventry city")
        self.assertEqual(import_standings.resolve("آرسنال", "en.1", teams, {}), "arsenal")
        self.assertEqual(import_standings.resolve("تیم ناشناخته", "en.1", teams, {}), None)

    def test_manual_mapping(self):
        teams = load_teams()
        manual = {import_standings.norm("نیوکسل"): "arsenal"}
        self.assertEqual(import_standings.resolve("نیوکسل", "en.1", teams, manual), "arsenal")


class TestOfficialStandings(unittest.TestCase):
    def test_loaded_tables_are_valid(self):
        official = load_official_standings()
        self.assertTrue(official, "دست‌کم یک جدول رسمی باید وارد شده باشد")
        for league, data in official.items():
            rows = data["rows"]
            self.assertGreaterEqual(len(rows), 18, league)
            points = [r["points"] for r in rows]
            self.assertEqual(points, sorted(points, reverse=True), league)
            for row in rows:
                self.assertEqual(row["played"], row["won"] + row["drawn"] + row["lost"], league)
                self.assertLessEqual(row["won"] * 3 + row["drawn"], row["points"] + 3)

    def test_predictor_returns_official_rows(self):
        predictor = LeaguePredictor("en.1")
        official = predictor.official_standings()
        if official is None:
            self.skipTest("جدول رسمی برای en.1 وارد نشده")
        self.assertEqual(len(official["rows"]), 20)
        self.assertEqual(official["rows"][0]["position"], 1)
        self.assertTrue(official["source"])
        self.assertTrue(official["updated_at"])

    def test_leagues_without_official_data(self):
        # لیگ‌هایی که جدول رسمی‌شان هنوز وارد نشده (در حال تکمیل)
        from football_predictor.dataset import load_official_standings

        imported = set(load_official_standings())
        missing = [lg for lg in ("en.1", "es.1", "de.1", "fr.1", "it.1", "nl.1", "pt.1") if lg not in imported]
        self.assertEqual(missing, [], f"جدول رسمی این لیگ‌ها وارد نشده: {missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class DuplicateMappingTests(unittest.TestCase):
    def test_two_names_mapping_to_one_team_is_rejected(self):
        import subprocess
        import tempfile
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        text = (
            "| # | تیم | بازی | برد | مساوی | باخت | گل -/+ | تفاضل | امتیاز |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| 1 | مونزا | 9 | 2 | 1 | 6 | 15-20 | -5 | 7 |\n"
            "| 2 | ونتزیا | 9 | 1 | 0 | 8 | 5-18 | -13 | 3 |\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as fh:
            fh.write(text)
            path = fh.name
        proc = subprocess.run(
            [
                "python3",
                str(root / "scripts" / "import_standings.py"),
                "--league", "it.1",
                "--file", path,
                "--date", "2026-11-01",
                "--expected", "2",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("monza", proc.stderr)


class OfficialLeagueOutsideModelTests(unittest.TestCase):
    def test_official_only_league_is_listed(self):
        from football_predictor.dataset import load_official_standings, load_leagues, official_leagues

        official = load_official_standings()
        listed = {l["id"]: l for l in official_leagues()}
        self.assertTrue(set(official).issubset(listed))
        model = load_leagues()
        for key, entry in listed.items():
            self.assertEqual(entry["official_only"], key not in model)
            self.assertTrue(entry["name_fa"])
            self.assertEqual(entry["teams"], len(official[key]["rows"]))

    def test_official_tables_are_internally_balanced(self):
        from football_predictor.dataset import load_official_standings

        for key, block in load_official_standings().items():
            rows = block["rows"]
            played = sum(r["played"] for r in rows)
            self.assertEqual(played % 2, 0, f"{key}: مجموع بازی‌ها باید زوج باشد")
            self.assertEqual(
                sum(r["gf"] for r in rows), sum(r["ga"] for r in rows), f"{key}: گل زده و خورده"
            )
            self.assertEqual(
                sum(r["won"] for r in rows), sum(r["lost"] for r in rows), f"{key}: برد و باخت"
            )
            self.assertEqual(sum(r["drawn"] for r in rows) % 2, 0, f"{key}: مساوی‌ها")
