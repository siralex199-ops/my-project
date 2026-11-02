#!/usr/bin/env python3
"""ورود جدول رسمی لیگ‌ها (مثلاً از varzesh3) به data/standings_official.json

استفاده: متن جدول را از صفحه‌ی «جدول لیگ» ورزش۳ کپی کنید و در یک فایل
(مثلاً /tmp/pl.md) بگذارید، سپس:

    python3 scripts/import_standings.py --league en.1 --file /tmp/pl.md --date 2026-10-31

جدول مارک‌داون ورزش۳ این شکل است:

    | # |  | تیم | بازی | برد | مساوی | باخت | گل -/+ | تفاضل  | امتیاز | بازی‌های اخیر |
    | 1 |  | آرسنال | 9 | 8 | 0 | 1 | 14-5 | 9 | 24 | L W W W W |

یا بدون ستون‌های اضافه (نسخه‌ی ساده‌تر سایت).

اگر نام تیمی با تیم‌های پروژه جور نشود، فهرست «نام‌های ناشناخته» چاپ می‌شود و
می‌توانید با --map "نام ورزش۳=کلید پروژه" آن را دستی نگاشت کنید.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from football_predictor.dataset import DATA_DIR, load_leagues, load_teams  # noqa: E402

OUT = DATA_DIR / "standings_official.json"
ZWNJ = "\u200c"


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace(ZWNJ, "").replace("\u200f", "").replace("\u200e", "")
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
    text = re.sub(r"[^\w\u0600-\u06FF]+", "", text)
    return text.strip().lower()


def parse_rows(text: str) -> list[list[str]]:
    """استخراج ردیف‌های جدول مارک‌داون."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 6:
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if any("تیم" in c for c in cells) or "بازی" in cells:
            continue
        rows.append(cells)
    return rows


NUMBER = re.compile(r"^-?\d+$")


GOALS = re.compile(r"^(\d+)\s*-\s*(\d+)$")


def row_to_record(cells: list[str]) -> dict | None:
    """تبدیل یک ردیف جدول به رکورد عددی.

    ستون گل در ورزش۳ به شکل «زده-خورده» (مثل 14-5) است و بقیه‌ی ستون‌ها عدد ساده.
    """
    gf = ga = None
    numbers: list[int] = []
    name_parts: list[str] = []

    for cell in cells:
        value = cell.replace("*", "").strip()
        goals = GOALS.match(value)
        if goals and gf is None:
            gf, ga = int(goals.group(1)), int(goals.group(2))
            continue
        if NUMBER.match(value):
            numbers.append(int(value))
        else:
            name_parts.append(value)

    # الگوی رایج: [رتبه, بازی, برد, مساوی, باخت, تفاضل, امتیاز]
    if len(numbers) < 6:
        return None
    rank = numbers[0]
    played, won, drawn, lost = numbers[1:5]
    points = numbers[-1]
    if played != won + drawn + lost:
        return None
    if gf is not None and ga is not None:
        diff = gf - ga
        if len(numbers) >= 7 and numbers[-2] != diff:
            # ستون تفاضل با محاسبه جور نیست؛ به داده اعتماد نکن
            return None

    name = ""
    for part in name_parts:
        cleaned = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", part)   # حذف تصویر
        cleaned = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cleaned)  # حذف لینک
        cleaned = cleaned.replace("**", "").strip()
        if cleaned and not NUMBER.match(cleaned):
            name = cleaned
            break
    if not name:
        return None

    return {
        "rank": rank,
        "name": name,
        "played": played,
        "won": won,
        "drawn": drawn,
        "lost": lost,
        "gf": gf,
        "ga": ga,
        "points": points,
    }


def resolve(name: str, league: str, teams: dict, manual: dict[str, str]) -> str | None:
    key = manual.get(norm(name))
    if key:
        return key
    candidates = {
        k: v for k, v in teams.items() if league in v.get("leagues", [])
    } or teams

    target = norm(name)
    for k, v in candidates.items():
        if target in {norm(v.get("fa", "")), norm(v.get("en", "")), norm(k)}:
            return k
    # تطبیق پیشوندی (مثل «کاونتری» با «کاونتری سیتی»)
    for k, v in candidates.items():
        fa = norm(v.get("fa", ""))
        if fa and (fa.startswith(target) or target.startswith(fa)) and abs(len(fa) - len(target)) <= 8:
            return k
    pool = {norm(v.get("fa", "")): k for k, v in candidates.items() if v.get("fa")}
    pool.update({norm(v.get("en", "")): k for k, v in candidates.items() if v.get("en")})
    close = difflib.get_close_matches(target, list(pool), n=1, cutoff=0.72)
    return pool[close[0]] if close else None


def main() -> int:
    ap = argparse.ArgumentParser(description="ورود جدول رسمی یک لیگ")
    ap.add_argument("--league", required=True)
    ap.add_argument("--file", required=True, help="فایل متنی شامل جدول کپی‌شده")
    ap.add_argument("--date", default=date.today().isoformat(), help="تاریخ به‌روزرسانی جدول")
    ap.add_argument("--source", default="varzesh3.com")
    ap.add_argument("--url", default="")
    ap.add_argument("--map", action="append", default=[], help="نگاشت دستی: \"نام سایت=کلید\"")
    ap.add_argument("--expected", type=int, default=None, help="تعداد تیم‌های مورد انتظار")
    args = ap.parse_args()

    if args.league not in load_leagues():
        print(f"لیگ ناشناخته: {args.league}", file=sys.stderr)
        return 1

    manual = {}
    for item in args.map:
        if "=" not in item:
            continue
        name, key = item.split("=", 1)
        manual[norm(name)] = key.strip()

    text = Path(args.file).read_text(encoding="utf-8")
    raw_rows = parse_rows(text)
    records = [r for r in (row_to_record(cells) for cells in raw_rows) if r]
    if not records:
        print("هیچ ردیف قابل‌استفاده‌ای در فایل پیدا نشد.", file=sys.stderr)
        return 1

    teams = load_teams()
    rows, unknown = [], []
    for rec in records:
        key = resolve(rec["name"], args.league, teams, manual)
        if not key:
            unknown.append(rec["name"])
            continue
        rows.append(
            {
                "team": key,
                "name": teams.get(key, {}).get("fa", rec["name"]),
                "played": rec["played"],
                "won": rec["won"],
                "drawn": rec["drawn"],
                "lost": rec["lost"],
                "gf": rec["gf"],
                "ga": rec["ga"],
                "points": rec["points"],
            }
        )

    rows.sort(key=lambda r: (-r["points"], -((r["gf"] or 0) - (r["ga"] or 0)), -(r["gf"] or 0)))
    for i, row in enumerate(rows, 1):
        row["position"] = i
        row["gd"] = (row["gf"] - row["ga"]) if row["gf"] is not None and row["ga"] is not None else None

    payload = {"source": args.source, "updated_at": args.date, "leagues": {}}
    if OUT.exists():
        payload = json.loads(OUT.read_text(encoding="utf-8"))
        payload.setdefault("leagues", {})
    payload["leagues"][args.league] = {
        "source": args.source,
        "source_url": args.url,
        "updated_at": args.date,
        "rows": rows,
    }
    payload["source"] = args.source
    payload["updated_at"] = args.date
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"✓ {len(rows)} تیم برای {args.league} ثبت شد (منبع: {args.source} · {args.date})")
    if unknown:
        print(f"! {len(unknown)} نام ناشناخته (با --map نگاشت کنید): {', '.join(unknown)}")
    if args.expected and len(rows) != args.expected:
        print(f"! هشدار: {len(rows)} تیم ثبت شد ولی {args.expected} انتظار می‌رفت.")
    print(f"  → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
