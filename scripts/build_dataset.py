#!/usr/bin/env python3
"""ساخت دیتاست بازی‌ها از مخزن openfootball/football.json.

استفاده:
    python3 scripts/build_dataset.py --source /path/to/football.json [--out data]

اگر --source داده نشود، آرشیو مخزن از GitHub دانلود و در پوشه‌ای موقت باز می‌شود.

خروجی:
    data/matches.csv   →  league,season,date,home,away,hg,ag
    data/teams.json    →  {team_key: {en, fa, leagues}}
    data/leagues.json  →  اطلاعات لیگ‌ها
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import tempfile
import unicodedata
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

ARCHIVE_URL = "https://codeload.github.com/openfootball/football.json/zip/refs/heads/master"

# لیگ‌هایی که مدل روی آن‌ها آموزش می‌بیند
LEAGUES = {
    "en.1": {"name_en": "Premier League", "name_fa": "لیگ برتر انگلیس", "country": "England", "flag": "🇬🇧", "tier": 1},
    "en.2": {"name_en": "Championship", "name_fa": "چمپیونشیپ انگلیس", "country": "England", "flag": "🇬🇧", "tier": 2},
    "es.1": {"name_en": "LaLiga", "name_fa": "لالیگا اسپانیا", "country": "Spain", "flag": "🇪🇸", "tier": 1},
    "it.1": {"name_en": "Serie A", "name_fa": "سری آ ایتالیا", "country": "Italy", "flag": "🇮🇹", "tier": 1},
    "de.1": {"name_en": "Bundesliga", "name_fa": "بوندس‌لیگا آلمان", "country": "Germany", "flag": "🇩🇪", "tier": 1},
    "fr.1": {"name_en": "Ligue 1", "name_fa": "لیگ ۱ فرانسه", "country": "France", "flag": "🇫🇷", "tier": 1},
    "nl.1": {"name_en": "Eredivisie", "name_fa": "ارِدیویزی هلند", "country": "Netherlands", "flag": "🇳🇱", "tier": 1},
    "pt.1": {"name_en": "Primeira Liga", "name_fa": "لیگ برتر پرتغال", "country": "Portugal", "flag": "🇵🇹", "tier": 1},
}

# واژه‌هایی که بخشی از نام رسمی باشگاه‌اند ولی برای تشخیص هویت باشگاه لازم نیستند
SUFFIX_TOKENS = {
    "fc", "afc", "cf", "sc", "ac", "ss", "ssc", "as", "rc", "cd", "ca", "ud", "sv",
    "vfl", "vfb", "tsg", "fsv", "bsc", "spvgg", "us", "sd", "acf", "cfc", "rcd",
    "sad", "sl", "gd", "cs", "sbv", "osc", "hsc", "fco", "estac", "aj", "ea", "sm",
    "ogc", "bc", "uc", "es",
}
STOP_TOKENS = {"de", "do", "da", "dos", "das", "der", "die", "des", "van", "von", "calcio", "clube", "ii", "1909"}

# نام‌های جایگزین (پس از نرمال‌سازی) → کلید یکتا
ALIASES = {
    # ایتالیا
    "internazionale milano": "inter",
    "lazio roma": "lazio",
    "delfino pescara": "pescara",
    "spal ferrara": "spal",
    "hellas verona": "verona",
    "chievo verona": "chievo",
    "atalanta bc": "atalanta",
    # هلند
    "psv eindhoven": "psv",
    "az alkmaar": "az",
    "nec nijmegen": "nec",
    "willem tilburg": "willem ii",
    "feyenoord rotterdam": "feyenoord",
    "cambuur leeuwarden": "cambuur",
    "vvv venlo": "vvv venlo",
    "graafschap": "de graafschap",
    "pec zwolle": "zwolle",
    # پرتغال
    "sporting portugal": "sporting",
    "sporting cp": "sporting",
    "sport lisboa e benfica": "benfica",
    "sporting braga": "braga",
    "sporting clube de braga": "braga",
    "estoril praia": "estoril",
    # اسپانیا
    "real betis balompie": "real betis",
    "real sociedad futbol": "real sociedad",
    "celta vigo": "celta",
    "rayo vallecano madrid": "rayo vallecano",
    "deportivo alaves": "alaves",
    "athletic club": "athletic bilbao",
    "club atletico madrid": "atletico madrid",
    "rc deportivo la coruna": "deportivo la coruna",
    "rcd espanyol de barcelona": "espanyol barcelona",
    "real racing club santander": "racing santander",
    "racing santander": "racing santander",
    # آلمان
    "bor monchengladbach": "borussia monchengladbach",
    "hamburger": "hamburg",
    "hertha": "hertha berlin",
    "rb leipzig": "rb leipzig",
    "bayern munchen": "bayern munich",
    "bayer leverkusen": "bayer leverkusen",
    "borussia dortmund": "borussia dortmund",
    # فرانسه
    "racing club lens": "lens",
    "strasbourg alsace": "strasbourg",
    "nancy lorraine": "nancy",
    "nimes olympique": "nimes",
    "girondins bordeaux": "bordeaux",
    "olympique lyonnais": "lyon",
    "olympique marseille": "marseille",
    "paris saint germain": "psg",
    "stade rennais": "rennes",
    "stade reims": "reims",
    "stade brestois": "brest",
    "clermont foot": "clermont",
    # انگلیس
    "queens park rangers": "qpr",
    "west bromwich albion": "west brom",
    "west ham united": "west ham",
    "wolverhampton wanderers": "wolves",
    "brighton and hove albion": "brighton",
    "tottenham hotspur": "tottenham",
    "huddersfield town": "huddersfield",
    "newcastle united": "newcastle",
    "nottingham forest": "nottingham forest",
    "leeds united": "leeds",
    "leicester city": "leicester",
    "stoke city": "stoke",
    "swansea city": "swansea",
    "cardiff city": "cardiff",
    "bristol city": "bristol city",
    "milton keynes dons": "mk dons",
    "preston north end": "preston",
    "rotherham united": "rotherham",
    "peterborough united": "peterborough",
    "oxford united": "oxford",
    "plymouth argyle": "plymouth",
    "wycombe wanderers": "wycombe",
    "charlton athletic": "charlton",
    "derby county": "derby",
    "doncaster rovers": "doncaster",
    "lincoln city": "lincoln",
    "scunthorpe united": "scunthorpe",
    "yeovil town": "yeovil",
    "birmingham city": "birmingham",
    "blackburn rovers": "blackburn",
    "bolton wanderers": "bolton",
    "wigan athletic": "wigan",
    "hull city": "hull",
    "willem": "willem ii",
}

# نام نمایشی انگلیسی (اختیاری؛ در نبود آن پرتکرارترین نام خام استفاده می‌شود)
DISPLAY_NAMES = {
    "psv": "PSV Eindhoven",
    "az": "AZ Alkmaar",
    "nec": "NEC Nijmegen",
    "vvv venlo": "VVV-Venlo",
    "willem ii": "Willem II",
    "rkc waalwijk": "RKC Waalwijk",
    "ado den haag": "ADO Den Haag",
    "go ahead eagles": "Go Ahead Eagles",
    "pec zwolle": "PEC Zwolle",
    "sparta rotterdam": "Sparta Rotterdam",
    "telstar": "Telstar",
    "qpr": "Queens Park Rangers",
    "mk dons": "MK Dons",
    "west brom": "West Bromwich Albion",
    "wolves": "Wolverhampton",
    "psg": "Paris Saint-Germain",
    "bayern munich": "Bayern Munich",
    "gladbach": "Borussia Mönchengladbach",
    "monchengladbach": "Borussia Mönchengladbach",
    "koln": "FC Köln",
    "milan": "AC Milan",
    "inter": "Inter Milan",
    "roma": "AS Roma",
    "lyon": "Olympique Lyonnais",
    "marseille": "Olympique Marseille",
    "rennes": "Stade Rennais",
    "reims": "Stade de Reims",
    "brest": "Stade Brestois",
    "saint etienne": "Saint-Étienne",
    "benfica": "Benfica",
    "sporting": "Sporting CP",
    "porto": "FC Porto",
    "braga": "SC Braga",
    "vitoria guimaraes": "Vitória Guimarães",
    "atletico madrid": "Atlético Madrid",
    "athletic bilbao": "Athletic Bilbao",
    "espanyol barcelona": "Espanyol",
    "celta": "Celta Vigo",
    "deportivo la coruna": "Deportivo La Coruña",
    "real betis": "Real Betis",
    "real sociedad": "Real Sociedad",
    "racing santander": "Racing Santander",
    "spal": "SPAL",
    "verona": "Hellas Verona",
    "pescara": "Pescara",
    "hertha berlin": "Hertha BSC",
    "hamburg": "Hamburger SV",
    "leipzig": "RB Leipzig",
    "leverkusen": "Bayer Leverkusen",
    "dortmund": "Borussia Dortmund",
    "frankfurt": "Eintracht Frankfurt",
    "bielefeld": "Arminia Bielefeld",
    "dusseldorf": "Fortuna Düsseldorf",
    "greuther furth": "Greuther Fürth",
    "kiel": "Holstein Kiel",
    "st pauli": "St. Pauli",
    "nurnberg": "1. FC Nürnberg",
    "hertha": "Hertha BSC",
    "de graafschap": "De Graafschap",
    "zwolle": "PEC Zwolle",
    "cambuur": "SC Cambuur",
    "nac breda": "NAC Breda",
    "estrela amadora": "Estrela da Amadora",
    "casa pia": "Casa Pia",
    "pacos ferreira": "Paços de Ferreira",
    "gil vicente": "Gil Vicente",
    "rio ave": "Rio Ave",
    "santa clara": "Santa Clara",
    "vitoria setubal": "Vitória Setúbal",
    "academico viseu": "Académico de Viseu",
    "belenenses": "Belenenses",
    "avs": "AVS",
    "aves": "CD Aves",
}


def normalize(name: str) -> str:
    """نرمال‌سازی نام باشگاه برای یکسان‌سازی املاهای مختلف."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("&", "and").replace(".", " ").replace("-", " ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    tokens = [t for t in s.split() if t and t not in SUFFIX_TOKENS and not t.isdigit() and t not in STOP_TOKENS]
    return " ".join(tokens)


def team_key(name: str) -> str:
    norm = normalize(name)
    return ALIASES.get(norm, norm)


def download_source() -> Path:
    """دانلود آرشیو مخزن داده و باز کردن آن در پوشه موقت."""
    tmp = Path(tempfile.mkdtemp(prefix="football-json-"))
    print(f"↓ دانلود داده از {ARCHIVE_URL}")
    with urllib.request.urlopen(ARCHIVE_URL, timeout=120) as resp:
        payload = resp.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        zf.extractall(tmp)
    roots = [p for p in tmp.iterdir() if p.is_dir()]
    if not roots:
        raise RuntimeError("آرشیو دانلودشده خالی است")
    return roots[0]


def season_sort_key(season: str) -> tuple[int, int]:
    m = re.match(r"^(\d{4})-(\d{2})$", season)
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2)))


def extract_scores(match: dict):
    score = match.get("score")
    if score is None:
        return None
    if isinstance(score, dict):
        ft = score.get("ft")
        if isinstance(ft, list) and len(ft) == 2 and None not in ft:
            return int(ft[0]), int(ft[1])
        return None
    if isinstance(score, list) and len(score) == 2 and None not in score:
        return int(score[0]), int(score[1])
    return None


def collect(source: Path):
    rows = []
    teams = defaultdict(lambda: {"raw": Counter(), "leagues": set()})

    for league in LEAGUES:
        files = sorted(
            (p for p in source.glob(f"*/{league}.json") if season_sort_key(p.parent.name) != (0, 0)),
            key=lambda p: season_sort_key(p.parent.name),
        )
        for path in files:
            season = path.parent.name
            payload = json.loads(path.read_text(encoding="utf-8"))
            for match in payload.get("matches", []):
                date = match.get("date")
                if not date:
                    continue
                home_raw, away_raw = match.get("team1"), match.get("team2")
                if not home_raw or not away_raw:
                    continue
                home, away = team_key(home_raw), team_key(away_raw)
                if home == away:
                    continue
                score = extract_scores(match)
                hg, ag = score if score else ("", "")
                rows.append(
                    {
                        "league": league,
                        "season": season,
                        "date": date,
                        "home": home,
                        "away": away,
                        "hg": hg,
                        "ag": ag,
                        "time": match.get("time", ""),
                        "round": match.get("round", ""),
                    }
                )
                for raw, key in ((home_raw, home), (away_raw, away)):
                    teams[key]["raw"][raw] += 1
                    teams[key]["leagues"].add(league)

    rows.sort(key=lambda r: (r["date"], r["league"]))
    return rows, teams


def main() -> int:
    ap = argparse.ArgumentParser(description="ساخت دیتاست بازی‌های فوتبال")
    ap.add_argument("--source", help="مسیر مخزن football.json (اختیاری)")
    ap.add_argument("--out", default=str(DATA), help="پوشه خروجی")
    args = ap.parse_args()

    source = Path(args.source) if args.source else download_source()
    if not source.exists():
        print(f"مسیر داده یافت نشد: {source}", file=sys.stderr)
        return 1

    rows, teams = collect(source)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "matches.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["league", "season", "date", "home", "away", "hg", "ag"])
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in writer.fieldnames})

    fa_names = {}
    fa_path = out_dir / "team_names_fa.json"
    if fa_path.exists():
        fa_names = json.loads(fa_path.read_text(encoding="utf-8"))

    teams_out = {}
    for key, info in sorted(teams.items()):
        raw_display = DISPLAY_NAMES.get(key) or (info["raw"].most_common(1)[0][0] if info["raw"] else key)
        entry = {
            "en": raw_display,
            "fa": fa_names.get(key, raw_display),
            "leagues": sorted(info["leagues"]),
        }
        teams_out[key] = entry

    (out_dir / "teams.json").write_text(json.dumps(teams_out, ensure_ascii=False, indent=1), encoding="utf-8")

    missing = [k for k in teams_out if k not in fa_names]
    (out_dir / "leagues.json").write_text(json.dumps(LEAGUES, ensure_ascii=False, indent=1), encoding="utf-8")

    scored = sum(1 for r in rows if r["hg"] != "")
    print(f"✓ {len(rows):,} بازی ثبت شد ({scored:,} بازی با نتیجه، {len(rows) - scored:,} بازی آینده)")
    print(f"✓ {len(teams_out)} تیم یکتا")
    if missing:
        print(f"! نام فارسی برای {len(missing)} تیم تعریف نشده: {', '.join(sorted(missing)[:10])}"
              + (" ..." if len(missing) > 10 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
