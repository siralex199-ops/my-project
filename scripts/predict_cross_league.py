#!/usr/bin/env python3
"""پیش‌بینی بازی بین دو تیم از دو لیگ مختلف (مثلاً لیگ قهرمانان اروپا).

قدرت حمله/دفاع هر تیم از مدل لیگ خودش گرفته می‌شود و به «ضریب نسبت به تیم
میانگین همان لیگ» تبدیل می‌شود؛ بعد با میانگین گل مسابقات آن رقابت ترکیب
می‌شود. این یک برآورد بین‌لیگی است، نه پیش‌بینی مدل برازش‌شده‌ی همان رقابت.

    python3 scripts/predict_cross_league.py --home بارسلونا --away "استون ویلا" \
        --comp-home 1.62 --comp-away 1.48
"""

from __future__ import annotations

import argparse
import difflib
import math
import re
import unicodedata
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from football_predictor.dataset import load_leagues, load_teams, resolve_team  # noqa: E402
from football_predictor.predictor import PredictorRegistry  # noqa: E402
from scripts.predict_open_match import build_matrix, summarise  # noqa: E402

REGISTRY = PredictorRegistry()


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200c", "").replace("\u200f", "").replace("\u200e", "")
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
    text = re.sub(r"[^\w\u0600-\u06FF]+", "", text)
    return text.strip().lower()


MANUAL = {
    "رم": "roma",
    "اینتر": "inter",
    "میلان": "milan",
    "پاری سن ژرمن": "psg",
    "منچستریونایتد": "manchester united",
}
PREFERRED = ["en.1", "es.1", "de.1", "it.1", "fr.1", "nl.1", "pt.1", "en.2", "it.2"]


def _league_of(key: str, info: dict) -> str:
    leagues = info.get("leagues") or []
    for lg in PREFERRED:
        if lg in leagues:
            return lg
    return leagues[0] if leagues else "en.1"


def find(team: str) -> tuple[str, str]:
    """(لیگ، کلید تیم) را از نام فارسی/انگلیسی پیدا می‌کند."""
    teams = load_teams()
    if team in MANUAL:
        key = MANUAL[team]
        return _league_of(key, teams[key]), key
    target = norm(team)
    for key, info in teams.items():
        for cand in (info.get("fa", ""), info.get("en", ""), key):
            if cand and norm(cand) == target:
                return _league_of(key, info), key
    pool = {}
    for key, info in teams.items():
        for cand in (info.get("fa", ""), info.get("en", ""), key):
            if cand:
                pool.setdefault(norm(cand), key)
    close = difflib.get_close_matches(target, list(pool), n=1, cutoff=0.8)
    if close:
        key = pool[close[0]]
        return _league_of(key, teams[key]), key
    raise SystemExit(f"تیم پیدا نشد: {team}")


def relative_strength(league: str, team: str) -> tuple[float, float]:
    predictor = REGISTRY.get(league)
    ratings = {r["team"]: r for r in predictor.power_table()}
    if team not in ratings:
        # تیم در آن فصل بازی نکرده؛ میانگین لیگ
        return 1.0, 1.0
    r = ratings[team]
    return math.exp(r["attack"]), math.exp(r["defence"])


def main() -> int:
    ap = argparse.ArgumentParser(description="پیش‌بینی بین‌لیگی")
    ap.add_argument("--home", required=True)
    ap.add_argument("--away", required=True)
    ap.add_argument("--comp-home", type=float, default=1.62, help="میانگین گل تیم میزبان در این رقابت")
    ap.add_argument("--comp-away", type=float, default=1.48, help="میانگین گل تیم میهمان در این رقابت")
    ap.add_argument("--rho", type=float, default=-0.05)
    ap.add_argument(
        "--gamma",
        type=float,
        default=0.7,
        help="فشرده‌سازی قدرت‌ها برای مقایسه بین‌لیگی (۱ = بدون فشردگی)",
    )
    args = ap.parse_args()

    hl, hk = find(args.home)
    al, ak = find(args.away)
    h_att, h_def = relative_strength(hl, hk)
    a_att, a_def = relative_strength(al, ak)
    lam = (h_att ** args.gamma) * (a_def ** args.gamma) * args.comp_home
    mu = (a_att ** args.gamma) * (h_def ** args.gamma) * args.comp_away
    res = summarise(build_matrix(lam, mu, args.rho))

    teams = load_teams()
    hname = teams.get(hk, {}).get("fa", hk)
    aname = teams.get(ak, {}).get("fa", ak)
    print(f"{hname} ({hl}) × {aname} ({al})")
    print(f"  گل انتظاری: {lam:.2f} - {mu:.2f}")
    print(
        f"  برد میزبان {res['home']*100:.1f}% | مساوی {res['draw']*100:.1f}% | "
        f"برد میهمان {res['away']*100:.1f}%"
    )
    print("  پراحتمال‌ترین نتایج: " + " , ".join(f"{h}-{a} ({p*100:.1f}%)" for h, a, p in res["scores"]))
    print("  بیشتر/کمتر: " + " | ".join(f"{line}: {p*100:.1f}%" for line, p in res["over"].items()))
    print(f"  هر دو گل می‌زنند: {res['btts']*100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
