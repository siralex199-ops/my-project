#!/usr/bin/env python3
"""اعتبارسنجی مدل به روش walk-forward روی فصل‌های گذشته.

برای هر فصل: مدل فقط با داده‌های قبل از شروع فصل آموزش می‌بیند و بعد روی
تمام بازی‌های آن فصل آزمایش می‌شود.

خروجی:	data/backtest.json  (برای نمایش در رابط وب)
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from football_predictor.dataset import load_leagues, matches_by_league  # noqa: E402
from football_predictor.model import DixonColes  # noqa: E402

SEASON_START_MONTH = 7  # شروع فصل اروپایی حدود تیر/مرداد


def season_start(season: str) -> date:
    year = int(season.split("-")[0])
    return date(year, SEASON_START_MONTH, 1)


def evaluate(predictions, actuals):
    """پیش‌بینی‌ها: لیست تاپل (p_home, p_draw, p_away) — نتیجه واقعی: 'H'/'D'/'A'."""
    n = len(predictions)
    if not n:
        return None
    logloss = acc = brier = 0.0
    for (ph, pd, pa), result in zip(predictions, actuals):
        probs = {"H": ph, "D": pd, "A": pa}
        logloss -= math.log(max(probs[result], 1e-12))
        acc += max(probs, key=probs.get) == result
        for key, p in probs.items():
            brier += (p - (1.0 if key == result else 0.0)) ** 2
    return {
        "matches": n,
        "accuracy": acc / n,
        "logloss": logloss / n,
        "brier": brier / n,
    }


def result_of(match) -> str:
    if match.home_goals > match.away_goals:
        return "H"
    if match.home_goals < match.away_goals:
        return "A"
    return "D"


def baseline(matches):
    """مدل ساده: نرخ پایه‌ی برد میزبان/مساوی/برد میهمان در کل تاریخچه."""
    home = draw = away = 0
    for m in matches:
        r = result_of(m)
        home += r == "H"
        draw += r == "D"
        away += r == "A"
    total = home + draw + away
    return home / total, draw / total, away / total


def main() -> int:
    ap = argparse.ArgumentParser(description="اعتبارسنجی مدل دیکسون-کولز")
    ap.add_argument("--seasons", default="2023-24,2024-25,2025-26", help="فصل‌های آزمایش")
    ap.add_argument("--history-years", type=int, default=5)
    ap.add_argument("--half-life", type=float, default=365.0)
    ap.add_argument("--out", default=str(ROOT / "data" / "backtest.json"))
    args = ap.parse_args()

    seasons = [s.strip() for s in args.seasons.split(",") if s.strip()]
    grouped = matches_by_league()
    leagues = load_leagues()

    all_predictions = []
    all_actuals = []
    per_season = []
    per_league: dict[str, list] = {key: [] for key in leagues}
    started = time.time()

    for season in seasons:
        start = season_start(season)
        season_predictions, season_actuals = [], []
        for league in leagues:
            matches = grouped.get(league, [])
            train = [
                m
                for m in matches
                if m.played and date(start.year - args.history_years, 7, 1) <= m.date < start
            ]
            test = [m for m in matches if m.played and m.season == season]
            if len(train) < 100 or not test:
                continue
            model = DixonColes(half_life_days=args.half_life, iterations=350).fit(
                train, as_of=start - timedelta(days=1)
            )
            for m in test:
                p = model.predict(m.home, m.away)
                trio = (p.prob_home, p.prob_draw, p.prob_away)
                season_predictions.append(trio)
                season_actuals.append(result_of(m))
                per_league[league].append((trio, result_of(m)))
        metrics = evaluate(season_predictions, season_actuals)
        if metrics:
            metrics["season"] = season
            per_season.append(metrics)
            all_predictions.extend(season_predictions)
            all_actuals.extend(season_actuals)
            print(
                f"فصل {season}: {metrics['matches']} بازی | "
                f"دقت {metrics['accuracy'] * 100:.1f}% | "
                f"log-loss {metrics['logloss']:.4f} | بریر {metrics['brier']:.4f}"
            )

    summary = evaluate(all_predictions, all_actuals)
    if not summary:
        print("داده کافی برای اعتبارسنجی نبود.", file=sys.stderr)
        return 1

    base = baseline([m for ms in grouped.values() for m in ms if m.played and m.date < date(2023, 7, 1)])
    base_preds = [base] * len(all_actuals)
    base_metrics = evaluate(base_preds, all_actuals)

    league_rows = []
    for key, rows in per_league.items():
        if not rows:
            continue
        metrics = evaluate([r[0] for r in rows], [r[1] for r in rows])
        metrics["league"] = key
        metrics["name_fa"] = leagues[key].get("name_fa", key)
        league_rows.append(metrics)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "settings": {
            "half_life_days": args.half_life,
            "history_years": args.history_years,
            "seasons": seasons,
        },
        "summary": {
            **summary,
            "baseline_accuracy": base_metrics["accuracy"],
            "baseline_logloss": base_metrics["logloss"],
            "baseline_brier": base_metrics["brier"],
            "baseline_probs": {"home": base[0], "draw": base[1], "away": base[2]},
        },
        "by_season": per_season,
        "by_league": sorted(league_rows, key=lambda r: -r["matches"]),
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n— خلاصه —")
    print(f"تعداد بازی: {summary['matches']:,}")
    print(f"دقت: {summary['accuracy'] * 100:.2f}%  (مدل ساده: {base_metrics['accuracy'] * 100:.2f}%)")
    print(f"log-loss: {summary['logloss']:.4f}  (مدل ساده: {base_metrics['logloss']:.4f})")
    print(f"امتیاز بریر: {summary['brier']:.4f}  (مدل ساده: {base_metrics['brier']:.4f})")
    print(f"زمان: {time.time() - started:.1f} ثانیه → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
