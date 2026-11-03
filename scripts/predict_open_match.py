#!/usr/bin/env python3
"""پیش‌بینی سریع برای بازی‌هایی که در دیتاست مدل نیستند (مثل لیگ نخبگان آسیا).

ورودی، آمار فصل جاری دو تیم در همان رقابت است (بازی، گل زده، گل خورده). آمار با
میانگین رقابت «کوچک» می‌شود تا نمونه‌های ۳-۴ بازی‌ای بیش از حد اثر نگذارند، سپس
دو میانگین گل انتظاری ساخته و ماتریس نتیجه با اصلاح دیکسون-کولز محاسبه می‌شود.

نمونه:

    python3 scripts/predict_open_match.py --home پاختاکور --away النصر \
        --home-played 4 --home-gf 4 --home-ga 9 \
        --away-played 3 --away-gf 9 --away-ga 7 \
        --league-avg 1.40 --shrink 4 --home-adv 1.08
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from football_predictor.model import MAX_GOALS, poisson_pmf, tau  # noqa: E402


def shrunk_rate(goals: float, played: int, league_avg: float, shrink: float) -> float:
    """نرخ گل تیم با میانگین‌گیری به سمت میانگین رقابت (پیشین = shrink بازی)."""
    prior = shrink * league_avg
    return (goals + prior) / (played + shrink)


def build_matrix(lam: float, mu: float, rho: float, max_goals: int = MAX_GOALS) -> list[list[float]]:
    size = max_goals + 1
    mp = [poisson_pmf(k, lam) for k in range(size)]
    mq = [poisson_pmf(k, mu) for k in range(size)]
    matrix = [[0.0] * size for _ in range(size)]
    total = 0.0
    for i in range(size):
        for j in range(size):
            p = mp[i] * mq[j] * tau(i, j, lam, mu, rho)
            matrix[i][j] = p
            total += p
    return [[c / total for c in row] for row in matrix]


def summarise(matrix: list[list[float]]) -> dict:
    home = draw = away = 0.0
    btts = 0.0
    over = {1.5: 0.0, 2.5: 0.0, 3.5: 0.0}
    scores = []
    for i, row in enumerate(matrix):
        for j, p in enumerate(row):
            if i > j:
                home += p
            elif i == j:
                draw += p
            else:
                away += p
            if i > 0 and j > 0:
                btts += p
            for line in over:
                if i + j > line:
                    over[line] += p
            scores.append((i, j, p))
    scores.sort(key=lambda s: -s[2])
    return {
        "home": home,
        "draw": draw,
        "away": away,
        "btts": btts,
        "over": over,
        "scores": scores[:6],
        "home_minus_1": sum(p for i, j, p in scores if i - j >= 2),
        "away_minus_1": sum(p for i, j, p in scores if j - i >= 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="پیش‌بینی سریع برای بازی خارج از دیتاست")
    ap.add_argument("--home", required=True)
    ap.add_argument("--away", required=True)
    ap.add_argument("--home-played", type=int, required=True)
    ap.add_argument("--home-gf", type=int, required=True)
    ap.add_argument("--home-ga", type=int, required=True)
    ap.add_argument("--away-played", type=int, required=True)
    ap.add_argument("--away-gf", type=int, required=True)
    ap.add_argument("--away-ga", type=int, required=True)
    ap.add_argument("--league-avg", type=float, default=1.40, help="میانگین گل هر تیم در هر بازی رقابت")
    ap.add_argument("--shrink", type=float, default=4.0, help="وزن پیشین (تعداد بازی معادل)")
    ap.add_argument("--home-adv", type=float, default=1.08, help="ضریب میزبانی روی گل انتظاری میزبان")
    ap.add_argument("--away-adv", type=float, default=0.94, help="ضریب مهمانی روی گل انتظاری میهمان")
    ap.add_argument("--neutral", action="store_true", help="زمین بی‌طرف (بدون مزیت میزبانی)")
    ap.add_argument("--rho", type=float, default=-0.05)
    args = ap.parse_args()

    avg = args.league_avg
    h_att = shrunk_rate(args.home_gf, args.home_played, avg, args.shrink) / avg
    h_def = shrunk_rate(args.home_ga, args.home_played, avg, args.shrink) / avg
    a_att = shrunk_rate(args.away_gf, args.away_played, avg, args.shrink) / avg
    a_def = shrunk_rate(args.away_ga, args.away_played, avg, args.shrink) / avg

    boost_h, boost_a = (1.0, 1.0) if args.neutral else (args.home_adv, args.away_adv)
    lam = h_att * a_def * avg * boost_h
    mu = a_att * h_def * avg * boost_a

    res = summarise(build_matrix(lam, mu, args.rho))
    print(f"{args.home} × {args.away}")
    print(f"  گل انتظاری: {lam:.2f} - {mu:.2f}")
    print(f"  برد میزبان {res['home']*100:.1f}% | مساوی {res['draw']*100:.1f}% | برد میهمان {res['away']*100:.1f}%")
    print(f"  شانس دوگانه: 1X {100*(res['home']+res['draw']):.1f}% | 12 {100*(res['home']+res['away']):.1f}% | X2 {100*(res['draw']+res['away']):.1f}%")
    print("  پراحتمال‌ترین نتایج: " + " , ".join(f"{h}-{a} ({p*100:.1f}%)" for h, a, p in res["scores"]))
    print("  بیشتر/کمتر: " + " | ".join(f"{line}: {p*100:.1f}%" for line, p in res["over"].items()))
    print(f"  هر دو گل می‌زنند: {res['btts']*100:.1f}%")
    print(f"  هندیکپ: میزبان ۱- {res['home_minus_1']*100:.1f}% | میهمان ۱- {res['away_minus_1']*100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
