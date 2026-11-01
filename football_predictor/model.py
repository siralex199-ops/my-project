"""مدل دیکسون-کولز برای پیش‌بینی نتیجه بازی‌های فوتبال.

مدل کلاسیک Dixon & Coles (1997):
    λ (گل‌های تیم میزبان) = exp(attack_host + defence_away + home_adv)
    μ (گل‌های تیم میهمان) = exp(attack_away + defence_host + home_adv * 0)

به‌علاوه ضریب τ برای اصلاح احتمال نتایج کم‌گل (۰-۰، ۱-۰، ۰-۱، ۱-۱) که
همبستگی بین گل‌های دو تیم را مدل می‌کند، وزن‌دهی زمانی (نتایج قدیمی‌تر
اهمیت کمتری دارند) و تنظیم L2 برای جلوگیری از بیش‌برازش.

تمام محاسبات با کتابخانه استاندارد پایتون انجام می‌شود (بدون numpy).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

MAX_GOALS = 12


def poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """ضریب اصلاح دیکسون-کولز برای نتایج کم‌گل."""
    if x == 0 and y == 0:
        return max(1e-12, 1.0 - lam * mu * rho)
    if x == 0 and y == 1:
        return max(1e-12, 1.0 + lam * rho)
    if x == 1 and y == 0:
        return max(1e-12, 1.0 + mu * rho)
    if x == 1 and y == 1:
        return max(1e-12, 1.0 - rho)
    return 1.0


@dataclass
class Rating:
    team: str
    attack: float  # توان حمله (لگاریتمی)
    defence: float  # ضعف دفاع (لگاریتمی؛ بالاتر = گل بیشتری می‌خورد)
    matches: float  # تعداد بازی مؤثر (با وزن زمانی)

    @property
    def power(self) -> float:
        """قدرت کلی تیم در مقیاس لگاریتمی گل."""
        return self.attack - self.defence


@dataclass
class Prediction:
    home: str
    away: str
    prob_home: float
    prob_draw: float
    prob_away: float
    expected_home_goals: float
    expected_away_goals: float
    scores: list[tuple[int, int, float]] = field(default_factory=list)
    matrix: list[list[float]] = field(default_factory=list)
    over_under: dict[str, float] = field(default_factory=dict)
    btts: float = 0.0
    home_attack: float = 0.0
    away_attack: float = 0.0
    home_defence: float = 0.0
    away_defence: float = 0.0

    @property
    def most_likely_score(self) -> tuple[int, int]:
        return (self.scores[0][0], self.scores[0][1]) if self.scores else (0, 0)

    @property
    def double_chance_home(self) -> float:
        return self.prob_home + self.prob_draw

    @property
    def double_chance_away(self) -> float:
        return self.prob_away + self.prob_draw

    def as_dict(self) -> dict:
        return {
            "home": self.home,
            "away": self.away,
            "prob_home": self.prob_home,
            "prob_draw": self.prob_draw,
            "prob_away": self.prob_away,
            "expected_home_goals": self.expected_home_goals,
            "expected_away_goals": self.expected_away_goals,
            "most_likely_score": list(self.most_likely_score),
            "top_scores": [
                {"home": h, "away": a, "prob": p} for h, a, p in self.scores[:8]
            ],
            "over_under": self.over_under,
            "btts": self.btts,
            "double_chance": {
                "1X": self.double_chance_home,
                "12": self.prob_home + self.prob_away,
                "X2": self.double_chance_away,
            },
        }


class DixonColes:
    """برازش مدل دیکسون-کولز با گرادیان صعودی (Adam) و وزن‌دهی زمانی."""

    def __init__(
        self,
        half_life_days: float = 240.0,
        ridge: float = 0.03,
        mean_penalty: float = 40.0,
        iterations: int = 500,
        learning_rate: float = 0.05,
        max_goals: int = MAX_GOALS,
        fixed_rho: float | None = None,
    ) -> None:
        self.half_life_days = half_life_days
        self.ridge = ridge
        self.mean_penalty = mean_penalty
        self.iterations = iterations
        self.learning_rate = learning_rate
        self.max_goals = max_goals
        self.fixed_rho = fixed_rho
        self.attack: dict[str, float] = {}
        self.defence: dict[str, float] = {}
        self.home_adv: float = 0.0
        self.rho: float = 0.0
        self.teams: list[str] = []
        self.loglik: float = 0.0
        self.n_matches: int = 0
        self.effective_matches: dict[str, float] = {}

    # ------------------------------------------------------------------ fit
    def fit(self, matches, as_of: date | None = None) -> "DixonColes":
        """برازش مدل روی بازی‌های دارای نتیجه.

        matches: دنباله‌ای از آبجکت‌هایی با فیلدهای date, home, away,
        home_goals, away_goals (مثلاً dataset.Match).
        """
        played = [m for m in matches if getattr(m, "home_goals", None) is not None]
        if not played:
            raise ValueError("برای برازش مدل حداقل یک بازی با نتیجه لازم است")
        as_of = as_of or max(m.date for m in played)

        teams = sorted({m.home for m in played} | {m.away for m in played})
        index = {t: i for i, t in enumerate(teams)}
        n = len(teams)

        weights = []
        home_goals = 0.0
        away_goals = 0.0
        wsum = 0.0
        for m in played:
            days = max(0, (as_of - m.date).days)
            w = 0.5 ** (days / self.half_life_days) if self.half_life_days > 0 else 1.0
            weights.append(w)
            home_goals += w * m.home_goals
            away_goals += w * m.away_goals
            wsum += w

        # فقط بازی‌هایی که وزن ناچیز ندارند (بیش از ۶ سال فاصله)
        keep = [i for i, w in enumerate(weights) if w > 1e-4]
        data = [
            (
                index[played[i].home],
                index[played[i].away],
                played[i].home_goals,
                played[i].away_goals,
                weights[i],
            )
            for i in keep
        ]

        # مقادیر اولیه
        attack = [0.0] * n
        defence = [0.0] * n
        home_adv = math.log(max(1.01, home_goals / max(away_goals, 1e-9)))
        rho = -0.05 if self.fixed_rho is None else self.fixed_rho

        # پارامترهای Adam
        params = attack + defence + [home_adv, rho]
        m1 = [0.0] * len(params)
        m2 = [0.0] * len(params)
        beta1, beta2, eps = 0.9, 0.999, 1e-8
        lr = self.learning_rate
        size = 2 * n + 2

        for step in range(1, self.iterations + 1):
            grad = [0.0] * size
            ll = 0.0
            for h, a, hg, ag, w in data:
                rho = params[2 * n + 1]
                lam = math.exp(params[h] + params[n + a] + params[2 * n])
                mu = math.exp(params[a] + params[n + h])
                lam = min(lam, 25.0)
                mu = min(mu, 25.0)

                ll += w * (
                    hg * math.log(lam) - lam + ag * math.log(mu) - mu
                )

                dlam = 0.0
                dmu = 0.0
                drho = 0.0
                if (hg, ag) in ((0, 0), (0, 1), (1, 0), (1, 1)):
                    if hg == 0 and ag == 0:
                        t = max(1e-9, 1.0 - lam * mu * rho)
                        ll += w * math.log(t)
                        dlam = -mu * rho / t
                        dmu = -lam * rho / t
                        drho = -lam * mu / t
                    elif hg == 0 and ag == 1:
                        t = max(1e-9, 1.0 + lam * rho)
                        ll += w * math.log(t)
                        dlam = rho / t
                        drho = lam / t
                    elif hg == 1 and ag == 0:
                        t = max(1e-9, 1.0 + mu * rho)
                        ll += w * math.log(t)
                        dmu = rho / t
                        drho = mu / t
                    else:
                        t = max(1e-9, 1.0 - rho)
                        ll += w * math.log(t)
                        drho = -1.0 / t

                g_home = w * ((hg - lam) + dlam * lam)
                g_away = w * ((ag - mu) + dmu * mu)

                grad[h] += g_home            # حمله میزبان
                grad[n + a] += g_home        # دفاع میهمان
                grad[2 * n] += g_home        # مزیت میزبانی
                grad[a] += g_away            # حمله میهمان
                grad[n + h] += g_away        # دفاع میزبان
                grad[2 * n + 1] += w * drho

            # تنظیم L2 + جریمه میانگین صفر (برای شناسایی‌پذیری مدل)
            mean_a = sum(params[:n]) / n
            mean_d = sum(params[n : 2 * n]) / n
            for i in range(n):
                grad[i] -= 2 * self.ridge * params[i]
                grad[n + i] -= 2 * self.ridge * params[n + i]
                ll -= self.ridge * params[i] ** 2 + self.ridge * params[n + i] ** 2
            mean_pen = self.mean_penalty
            for i in range(n):
                grad[i] -= mean_pen * mean_a / n
                grad[n + i] -= mean_pen * mean_d / n
            ll -= 0.5 * mean_pen * (mean_a**2 + mean_d**2)

            # گام Adam
            for i in range(size):
                m1[i] = beta1 * m1[i] + (1 - beta1) * grad[i]
                m2[i] = beta2 * m2[i] + (1 - beta2) * grad[i] ** 2
                m1_hat = m1[i] / (1 - beta1**step)
                m2_hat = m2[i] / (1 - beta2**step)
                params[i] += lr * m1_hat / (math.sqrt(m2_hat) + eps)

            # محدودسازی برای پایداری
            for i in range(n):
                params[i] = max(-2.0, min(2.0, params[i]))
                params[n + i] = max(-2.0, min(2.0, params[n + i]))
            params[2 * n] = max(-0.6, min(1.0, params[2 * n]))
            if self.fixed_rho is None:
                params[2 * n + 1] = max(-0.35, min(0.35, params[2 * n + 1]))
            else:
                params[2 * n + 1] = self.fixed_rho

            self.loglik = ll

        self.teams = teams
        self.attack = {t: params[i] for i, t in enumerate(teams)}
        self.defence = {t: params[n + i] for i, t in enumerate(teams)}
        self.home_adv = params[2 * n]
        self.rho = params[2 * n + 1]
        self.n_matches = len(data)

        eff = {t: 0.0 for t in teams}
        for h, a, _hg, _ag, w in data:
            eff[teams[h]] += w
            eff[teams[a]] += w
        self.effective_matches = eff
        return self

    # ------------------------------------------------------------- helpers
    def rating(self, team: str) -> Rating:
        return Rating(
            team=team,
            attack=self.attack.get(team, 0.0),
            defence=self.defence.get(team, 0.0),
            matches=self.effective_matches.get(team, 0.0),
        )

    def rankings(self) -> list[Rating]:
        return sorted(
            (self.rating(t) for t in self.teams),
            key=lambda r: r.power,
            reverse=True,
        )

    def goal_rates(self, home: str, away: str) -> tuple[float, float]:
        """میانگین گل انتظاری دو تیم."""
        lam = math.exp(
            self.attack.get(home, 0.0) + self.defence.get(away, 0.0) + self.home_adv
        )
        mu = math.exp(self.attack.get(away, 0.0) + self.defence.get(home, 0.0))
        return lam, mu

    def score_matrix(self, home: str, away: str) -> list[list[float]]:
        lam, mu = self.goal_rates(home, away)
        size = self.max_goals + 1
        home_pmf = [poisson_pmf(k, lam) for k in range(size)]
        away_pmf = [poisson_pmf(k, mu) for k in range(size)]
        matrix = [[0.0] * size for _ in range(size)]
        total = 0.0
        for i in range(size):
            for j in range(size):
                p = home_pmf[i] * away_pmf[j] * tau(i, j, lam, mu, self.rho)
                matrix[i][j] = p
                total += p
        # نرمال‌سازی (به‌دلیل بریدن توزیع پواسون در MAX_GOALS)
        for i in range(size):
            for j in range(size):
                matrix[i][j] /= total
        return matrix

    # ------------------------------------------------------------ predict
    def predict(self, home: str, away: str, max_goals: int | None = None) -> Prediction:
        matrix = self.score_matrix(home, away)
        lam, mu = self.goal_rates(home, away)

        prob_home = prob_draw = prob_away = 0.0
        over = {1.5: 0.0, 2.5: 0.0, 3.5: 0.0}
        btts = 0.0
        scores: list[tuple[int, int, float]] = []
        for i, row in enumerate(matrix):
            for j, p in enumerate(row):
                if i > j:
                    prob_home += p
                elif i == j:
                    prob_draw += p
                else:
                    prob_away += p
                total = i + j
                for line in over:
                    if total > line:
                        over[line] += p
                if i > 0 and j > 0:
                    btts += p
                scores.append((i, j, p))
        scores.sort(key=lambda s: s[2], reverse=True)

        return Prediction(
            home=home,
            away=away,
            prob_home=prob_home,
            prob_draw=prob_draw,
            prob_away=prob_away,
            expected_home_goals=lam,
            expected_away_goals=mu,
            scores=scores[:10],
            matrix=matrix,
            over_under={
                "over_1_5": over[1.5],
                "over_2_5": over[2.5],
                "over_3_5": over[3.5],
                "under_2_5": 1.0 - over[2.5],
            },
            btts=btts,
            home_attack=self.attack.get(home, 0.0),
            away_attack=self.attack.get(away, 0.0),
            home_defence=self.defence.get(home, 0.0),
            away_defence=self.defence.get(away, 0.0),
        )
