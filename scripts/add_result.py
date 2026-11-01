#!/usr/bin/env python3
"""ثبت نتیجه‌ی یک بازی در data/manual_results.csv.

این فایل بعد از هر بار بازسازی دیتاست هم حفظ می‌شود و هنگام بارگذاری روی
نتایج پایه اعمال می‌شود.

نمونه:
    python3 scripts/add_result.py --league es.1 --home "الچه" --away "والنسیا" --score 0-1
    python3 scripts/add_result.py --league es.1 --home elche --away valencia --score 0-1 --date 2026-11-01
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from football_predictor.dataset import (  # noqa: E402
    DATA_DIR,
    MANUAL_RESULTS,
    load_leagues,
    resolve_team,
    team_name,
)

FIELDS = ["league", "season", "date", "home", "away", "hg", "ag"]


def main() -> int:
    ap = argparse.ArgumentParser(description="ثبت نتیجه‌ی بازی در دیتاست")
    ap.add_argument("--league", required=True, help="کلید لیگ، مثلاً es.1")
    ap.add_argument("--home", required=True, help="تیم میزبان (فارسی، انگلیسی یا کلید)")
    ap.add_argument("--away", required=True, help="تیم میهمان")
    ap.add_argument("--score", required=True, help="نتیجه مثل 2-1 (میزبان-میهمان)")
    ap.add_argument("--date", default=date.today().isoformat(), help="تاریخ بازی (YYYY-MM-DD)")
    ap.add_argument("--season", default=None, help="فصل، به‌طور پیش‌فرض از تاریخ حدس زده می‌شود")
    args = ap.parse_args()

    if args.league not in load_leagues():
        print(f"لیگ ناشناخته: {args.league}", file=sys.stderr)
        return 1
    try:
        home = resolve_team(args.home, args.league)
        away = resolve_team(args.away, args.league)
    except KeyError as exc:
        print(exc, file=sys.stderr)
        return 1
    if home == away:
        print("میزبان و میهمان نمی‌توانند یکی باشند.", file=sys.stderr)
        return 1

    try:
        hg_str, ag_str = args.score.replace(":", "-").split("-")
        hg, ag = int(hg_str), int(ag_str)
    except ValueError:
        print("قالب نتیجه باید مانند 2-1 باشد.", file=sys.stderr)
        return 1

    day = date.fromisoformat(args.date)
    season = args.season
    if season is None:
        season = f"{day.year}-{str(day.year + 1)[-2:]}" if day.month >= 7 else f"{day.year - 1}-{str(day.year)[-2:]}"

    rows = []
    if MANUAL_RESULTS.exists():
        with MANUAL_RESULTS.open(encoding="utf-8", newline="") as fh:
            rows = [
                r for r in csv.DictReader(fh)
                if not (r["league"] == args.league and r["home"] == home and r["away"] == away and r["date"] == day.isoformat())
            ]
    rows.append(
        {
            "league": args.league,
            "season": season,
            "date": day.isoformat(),
            "home": home,
            "away": away,
            "hg": hg,
            "ag": ag,
        }
    )
    rows.sort(key=lambda r: (r["league"], r["date"], r["home"]))

    with MANUAL_RESULTS.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✓ ثبت شد: {team_name(home)} {hg}-{ag} {team_name(away)}  ({day.isoformat()} · {args.league})")
    print(f"  {MANUAL_RESULTS.relative_to(ROOT)} — مجموع {len(rows)} نتیجه‌ی دستی")

    base = DATA_DIR / "matches.csv"
    exists = False
    if base.exists():
        with base.open(encoding="utf-8", newline="") as fh:
            exists = any(
                r["league"] == args.league
                and r["home"] == home
                and r["away"] == away
                and r["date"] == day.isoformat()
                for r in csv.DictReader(fh)
            )
    if not exists:
        print("! توجه: این بازی در برنامه‌ی رسمی لیگ پیدا نشد و به‌عنوان بازی جدید اضافه شد.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
