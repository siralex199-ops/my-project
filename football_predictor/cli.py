"""رابط خط فرمان برای پیش‌بینی بازی‌های فوتبال.

نمونه‌ها:
    python3 -m football_predictor.cli leagues
    python3 -m football_predictor.cli fixtures --league en.1 --limit 8
    python3 -m football_predictor.cli predict "آرسنال" "چلسی"
    python3 -m football_predictor.cli power --league en.1 --limit 10
    python3 -m football_predictor.cli table --league es.1
    python3 -m football_predictor.cli simulate --league it.1 --runs 2000
"""

from __future__ import annotations

import argparse
import sys

from .dataset import load_leagues, resolve_team, team_name
from .predictor import PredictorRegistry


def pct(value: float) -> str:
    return f"{value * 100:5.1f}%"


def bar(value: float, width: int = 22) -> str:
    filled = int(round(value * width))
    return "█" * filled + "·" * (width - filled)


def cmd_leagues(reg: PredictorRegistry, args) -> int:
    print(f"{'کلید':<8}{'لیگ':<24}{'فصل':<12}{'تیم':>5}{'بازی پیش‌رو':>12}")
    print("-" * 64)
    for info in reg.leagues():
        print(
            f"{info['id']:<8}{info['name_fa']:<24}{info['season']:<12}"
            f"{info['teams']:>5}{info['fixtures']:>12}"
        )
    return 0


def cmd_fixtures(reg: PredictorRegistry, args) -> int:
    predictor = reg.get(args.league)
    fixtures = predictor.fixtures(limit=args.limit)
    if not fixtures:
        print("بازی پیش‌رویی در داده‌ها نیست.")
        return 0
    title = load_leagues().get(args.league, {}).get("name_fa", args.league)
    print(f"\n{title} — فصل {predictor.season}")
    print("=" * 78)
    for f in fixtures:
        p = f.prediction
        date = f.match.date.isoformat()
        home, away = team_name(f.match.home), team_name(f.match.away)
        print(f"\n{date}   {home}  ×  {away}")
        print(f"   ۱ (میزبان) {pct(p.prob_home)}   مساوی {pct(p.prob_draw)}   ۲ (میهمان) {pct(p.prob_away)}")
        print(f"   گل انتظاری: {p.expected_home_goals:.2f} - {p.expected_away_goals:.2f}"
              f"   |   محتمل‌ترین نتیجه: {p.most_likely_score[0]}-{p.most_likely_score[1]}"
              f"   |   بالای ۲.۵ گل: {pct(p.over_under['over_2_5'])}"
              f"   |   هر دو گل می‌زنند: {pct(p.btts)}")
    return 0


def _guess_league(reg: PredictorRegistry, home_q: str, away_q: str) -> str:
    best, best_score = None, -1
    for info in reg.leagues():
        try:
            predictor = reg.get(info["id"])
            teams = set(predictor.teams())
            resolve_team(home_q, info["id"])
            resolve_team(away_q, info["id"])
        except KeyError:
            continue
        current = predictor.season_matches()
        pairs = {(m.home, m.away) for m in current}
        home_key = resolve_team(home_q, info["id"])
        away_key = resolve_team(away_q, info["id"])
        score = (3 if (home_key, away_key) in pairs else 0) + 1
        if score > best_score:
            best, best_score = info["id"], score
    if best is None:
        raise SystemExit("تیم‌ها پیدا نشدند؛ نام لیگ را با --league مشخص کنید.")
    return best


def cmd_predict(reg: PredictorRegistry, args) -> int:
    league = args.league or _guess_league(reg, args.home, args.away)
    predictor = reg.get(league)
    home = resolve_team(args.home, league)
    away = resolve_team(args.away, league)
    p = predictor.predict(home, away)
    league_name = load_leagues().get(league, {}).get("name_fa", league)

    print(f"\n{league_name} — فصل {predictor.season}")
    print("=" * 66)
    print(f"  {team_name(home)}   ×   {team_name(away)}")
    print("=" * 66)
    print(f"\n  برد میزبان    {pct(p.prob_home)}  {bar(p.prob_home)}")
    print(f"  مساوی         {pct(p.prob_draw)}  {bar(p.prob_draw)}")
    print(f"  برد میهمان    {pct(p.prob_away)}  {bar(p.prob_away)}")
    print(f"\n  شانس دوگانه:   ۱X {pct(p.double_chance_home)}   "
          f"۱۲ {pct(p.prob_home + p.prob_away)}   X۲ {pct(p.double_chance_away)}")
    print(f"\n  گل انتظاری: {p.expected_home_goals:.2f} - {p.expected_away_goals:.2f}"
          f"   (مجموع {p.expected_home_goals + p.expected_away_goals:.2f})")
    print(f"  بالای ۱.۵ گل: {pct(p.over_under['over_1_5'])}   "
          f"بالای ۲.۵: {pct(p.over_under['over_2_5'])}   "
          f"بالای ۳.۵: {pct(p.over_under['over_3_5'])}")
    print(f"  هر دو گل می‌زنند: {pct(p.btts)}")

    print("\n  محتمل‌ترین نتایج:")
    for h, a, prob in p.scores[:6]:
        print(f"    {h}-{a}   {pct(prob)}")
    print()
    return 0


def cmd_power(reg: PredictorRegistry, args) -> int:
    predictor = reg.get(args.league)
    rows = predictor.power_table()[: args.limit]
    league_name = load_leagues().get(args.league, {}).get("name_fa", args.league)
    print(f"\nقدرت تیم‌ها — {league_name} (فصل {predictor.season})")
    print("=" * 60)
    print(f"{'#':<4}{'تیم':<24}{'حمله':>8}{'دفاع':>8}{'قدرت':>8}")
    print("-" * 60)
    for row in rows:
        print(
            f"{row['rank']:<4}{row['name']:<24}{row['attack']:>+8.2f}"
            f"{row['defence']:>+8.2f}{row['power']:>+8.2f}"
        )
    print("\nحمله بالاتر = گل‌زنی بیشتر | دفاع پایین‌تر = گل خوردن کمتر | قدرت = حمله − دفاع")
    return 0


def cmd_table(reg: PredictorRegistry, args) -> int:
    predictor = reg.get(args.league)
    rows = predictor.standings()[: args.limit]
    league_name = load_leagues().get(args.league, {}).get("name_fa", args.league)
    print(f"\nجدول {league_name} — فصل {predictor.season}")
    print("=" * 66)
    print(f"{'#':<4}{'تیم':<24}{'بازی':>5}{'برد':>5}{'مساوی':>6}{'باخت':>6}{'امتیاز':>7}")
    print("-" * 66)
    for row in rows:
        print(
            f"{row['position']:<4}{row['name']:<24}{row['played']:>5}{row['won']:>5}"
            f"{row['drawn']:>6}{row['lost']:>6}{row['points']:>7}"
        )
    return 0


def cmd_simulate(reg: PredictorRegistry, args) -> int:
    predictor = reg.get(args.league)
    rows = reg.simulate(args.league, runs=args.runs)[: args.limit]
    league_name = load_leagues().get(args.league, {}).get("name_fa", args.league)
    print(f"\nشبیه‌سازی ادامه فصل — {league_name} ({args.runs} اجرا)")
    print("=" * 74)
    print(f"{'#':<4}{'تیم':<24}{'امتیاز فعلی':>12}{'امتیاز پیش‌بینی':>15}{'قهرمانی':>10}{'سقوط':>8}")
    print("-" * 74)
    for row in rows:
        print(
            f"{row['projected_rank']:<4}{row['name']:<24}{row['current_points']:>12}"
            f"{row['exp_points']:>15.1f}{pct(row['title_prob']):>10}{pct(row['relegation_prob']):>8}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="football_predictor",
        description="پیش‌بینی بازی‌های فوتبال با مدل دیکسون-کولز",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("leagues", help="فهرست لیگ‌های موجود")
    p.set_defaults(func=cmd_leagues)

    p = sub.add_parser("fixtures", help="پیش‌بینی بازی‌های پیش‌رو")
    p.add_argument("--league", default="en.1")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_fixtures)

    p = sub.add_parser("predict", help="پیش‌بینی یک بازی مشخص")
    p.add_argument("home", help="تیم میزبان (فارسی یا انگلیسی)")
    p.add_argument("away", help="تیم میهمان (فارسی یا انگلیسی)")
    p.add_argument("--league", default=None)
    p.set_defaults(func=cmd_predict)

    p = sub.add_parser("power", help="رتبه‌بندی قدرت تیم‌ها")
    p.add_argument("--league", default="en.1")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_power)

    p = sub.add_parser("table", help="جدول لیگ")
    p.add_argument("--league", default="en.1")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_table)

    p = sub.add_parser("simulate", help="شبیه‌سازی مونت‌کارلوی ادامه فصل")
    p.add_argument("--league", default="en.1")
    p.add_argument("--runs", type=int, default=1500)
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_simulate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    reg = PredictorRegistry()
    try:
        return args.func(reg, args)
    except KeyError as exc:
        print(f"خطا: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
