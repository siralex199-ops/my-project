#!/usr/bin/env python3
"""سرور وب پیش‌بینی فوتبال — فقط با کتابخانه استاندارد پایتون.

اجرا:
    python3 web/server.py            # روی پورت ۸۰۰۰
    PORT=5000 python3 web/server.py
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import traceback
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from football_predictor.dataset import (  # noqa: E402
    load_leagues,
    load_official_standings,
    official_leagues,
    load_matches,
    load_teams,
    resolve_team,
    team_name,
)
from football_predictor.predictor import PredictorRegistry  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
REGISTRY = PredictorRegistry()
BACKTEST_FILE = ROOT / "data" / "backtest.json"


def json_bytes(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "FootballPredictor/1.0"

    # ------------------------------------------------------------ helpers
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if content_type.startswith("application/json") else "max-age=120")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status: int = 200) -> None:
        self._send(status, json_bytes(payload), "application/json; charset=utf-8")

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status)

    def log_message(self, fmt: str, *args) -> None:  # quieter logs
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---------------------------------------------------------------- API
    def do_HEAD(self) -> None:  # noqa: N802
        """پاسخ به درخواست‌های HEAD (بررسی سلامت توسط پراکسی‌ها)."""
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            return
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            self.send_response(404)
            self.end_headers()
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path

        try:
            if path.startswith("/api/"):
                return self._api(path, query)
            return self._static(path)
        except KeyError as exc:
            return self._error(f"یافت نشد: {exc}", 404)
        except Exception as exc:  # pragma: no cover - defensive
            traceback.print_exc()
            return self._error(f"خطای داخلی: {exc}", 500)

    def _api(self, path: str, query: dict) -> None:
        league = (query.get("league", ["en.1"])[0] or "en.1").strip()
        limit = int(query.get("limit", ["30"])[0])

        if path == "/api/leagues":
            leagues = REGISTRY.leagues()
            seen = {l["id"] for l in leagues}
            # لیگ‌هایی که فقط جدول رسمی دارند (خارج از دیتاست مدل)
            leagues += [l for l in official_leagues() if l["id"] not in seen]
            return self._json({"leagues": leagues, "as_of": REGISTRY.as_of.isoformat()})

        if path == "/api/teams":
            predictor = REGISTRY.get(league)
            teams = [{"id": t, "name": team_name(t)} for t in predictor.teams()]
            return self._json({"league": league, "season": predictor.season, "teams": teams})

        if path == "/api/fixtures":
            predictor = REGISTRY.get(league)
            fixtures = predictor.fixtures(limit=max(1, min(limit, 200)))
            return self._json(
                {
                    "league": league,
                    "season": predictor.season,
                    "fixtures": [f.as_dict() for f in fixtures],
                }
            )

        if path == "/api/predict":
            home_q = query.get("home", [""])[0]
            away_q = query.get("away", [""])[0]
            if not home_q or not away_q:
                return self._error("پارامترهای home و away لازم است")
            predictor = REGISTRY.get(league)
            home = resolve_team(home_q, league)
            away = resolve_team(away_q, league)
            if home == away:
                return self._error("تیم میزبان و میهمان نمی‌توانند یکی باشند")
            prediction = predictor.predict(home, away)
            payload = prediction.as_dict()
            payload.update(
                {
                    "league": league,
                    "season": predictor.season,
                    "home_fa": team_name(home),
                    "away_fa": team_name(away),
                    "matrix": prediction.matrix[:7],
                    "matrix_labels": list(range(7)),
                }
            )
            return self._json(payload)

        if path == "/api/table":
            if league not in load_leagues():
                block = (load_official_standings() or {}).get(league)
                if not block:
                    return self._error(f"لیگ ناشناخته: {league}", 404)
                return self._json(
                    {
                        "league": league,
                        "season": "",
                        "default_source": "official",
                        "official": block,
                        "model": None,
                    }
                )
            predictor = REGISTRY.get(league)
            official = predictor.official_standings()
            return self._json(
                {
                    "league": league,
                    "season": predictor.season,
                    "default_source": "official" if official else "model",
                    "official": official,
                    "model": {"rows": predictor.standings()},
                }
            )

        if path == "/api/power":
            predictor = REGISTRY.get(league)
            return self._json({"league": league, "season": predictor.season, "power": predictor.power_table()})

        if path == "/api/simulate":
            runs = int(query.get("runs", ["1500"])[0])
            runs = max(100, min(runs, 4000))
            rows = REGISTRY.simulate(league, runs=runs)
            return self._json({"league": league, "runs": runs, "simulation": rows})

        if path == "/api/meta":
            backtest = {}
            if BACKTEST_FILE.exists():
                backtest = json.loads(BACKTEST_FILE.read_text(encoding="utf-8"))
            matches = load_matches()
            last_date = max(m.date for m in matches if m.played)
            return self._json(
                {
                    "as_of": REGISTRY.as_of.isoformat(),
                    "data_through": last_date.isoformat(),
                    "matches": len(matches),
                    "teams": len(load_teams()),
                    "leagues": len(load_leagues()),
                    "backtest": backtest,
                    "model": {
                        "name": "Dixon-Coles",
                        "half_life_days": 365,
                        "features": ["قدرت حمله", "قدرت دفاع", "مزیت میزبانی", "وزن‌دهی زمانی", "اصلاح نتایج کم‌گل"],
                    },
                }
            )

        return self._error("مسیر API ناشناخته است", 404)

    # ------------------------------------------------------------- static
    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            return self._error("فایل پیدا نشد", 404)
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype == "application/javascript":
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)


def main() -> int:
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f"⚽ سرور پیش‌بینی فوتبال روی http://{host}:{port} بالا آمد")
    print(f"   داده‌ها: {len(load_matches()):,} بازی | تاریخ مرجع: {date.today().isoformat()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nخداحافظ!")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
