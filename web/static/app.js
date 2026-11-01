/* پیش‌بین فوتبال — منطق رابط کاربری */

const state = {
  league: "en.1",
  view: "fixtures",
  leagues: [],
  teams: [],
  meta: null,
  leaguePanel: "table",
  simCache: {},
};

/* ─────────────────────────── ابزارها ─────────────────────────── */

const FA_DIGITS = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"];
const fa = (value) => String(value).replace(/\d/g, (d) => FA_DIGITS[+d]);
const pct = (v) => fa((v * 100).toFixed(1)) + "٪";
const pct0 = (v) => fa(Math.round(v * 100)) + "٪";
const num = (v, d = 2) => fa(Number(v).toFixed(d));

const MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"];
const WEEKDAYS = ["یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه"];

function toJalali(gy, gm, gd) {
  const gdm = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
  let jy = gy <= 1600 ? 0 : 979;
  gy -= gy <= 1600 ? 621 : 1600;
  const gy2 = gm > 2 ? gy + 1 : gy;
  let days =
    365 * gy +
    Math.floor((gy2 + 3) / 4) -
    Math.floor((gy2 + 99) / 100) +
    Math.floor((gy2 + 399) / 400) -
    80 +
    gd +
    gdm[gm - 1];
  jy += 33 * Math.floor(days / 12053);
  days %= 12053;
  jy += 4 * Math.floor(days / 1461);
  days %= 1461;
  if (days > 365) {
    jy += Math.floor((days - 1) / 365);
    days = (days - 1) % 365;
  }
  const jm = days < 186 ? 1 + Math.floor(days / 31) : 7 + Math.floor((days - 186) / 30);
  const jd = 1 + (days < 186 ? days % 31 : (days - 186) % 30);
  return [jy, jm, jd];
}

function formatDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  const [jy, jm, jd] = toJalali(y, m, d);
  const weekday = WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
  return `${weekday} ${fa(jd)} ${MONTHS[jm - 1]} ${fa(jy)}`;
}

const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, params = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    let msg = `خطا (${res.status})`;
    try {
      msg = (await res.json()).error || msg;
    } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
}

const errorBox = (msg) => `<div class="error-box">⚠️ ${escapeHtml(msg)}</div>`;

/* ─────────────────────────── راه‌اندازی ─────────────────────────── */

async function init() {
  bindEvents();
  try {
    const [leagues, meta] = await Promise.all([api("/api/leagues"), api("/api/meta")]);
    state.leagues = leagues.leagues;
    state.meta = meta;
    const known = state.leagues.some((l) => l.id === state.league);
    if (!known && state.leagues.length) state.league = state.leagues[0].id;
    renderChips();
    renderMeta();
    await loadFixtures();
  } catch (err) {
    document.getElementById("fixturesGrid").innerHTML = errorBox(err.message);
    document.getElementById("dataMeta").innerHTML = "⚠️ اتصال برقرار نشد";
  }
}

function bindEvents() {
  document.getElementById("tabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".tab");
    if (!btn) return;
    switchView(btn.dataset.view);
  });
  document.getElementById("leagueChips").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    selectLeague(chip.dataset.league);
  });
  document.getElementById("modal").addEventListener("click", (e) => {
    if (e.target.dataset.close !== undefined) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });
  document.getElementById("swapBtn").addEventListener("click", () => {
    const h = document.getElementById("homeSelect");
    const a = document.getElementById("awaySelect");
    [h.value, a.value] = [a.value, h.value];
  });
  document.getElementById("predictBtn").addEventListener("click", runManualPrediction);
  document.getElementById("leagueSwitch").addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    state.leaguePanel = btn.dataset.panel;
    document.querySelectorAll("#leagueSwitch button").forEach((b) => b.classList.toggle("active", b === btn));
    document.getElementById("tablePanel").classList.toggle("hidden", state.leaguePanel !== "table");
    document.getElementById("powerPanel").classList.toggle("hidden", state.leaguePanel !== "power");
  });
  document.getElementById("simRefresh").addEventListener("click", () => {
    state.simCache[state.league] = null;
    loadSimulation();
  });
  document.getElementById("fixturesGrid").addEventListener("click", (e) => {
    const card = e.target.closest(".match-card");
    if (card) openDetail(card.dataset.home, card.dataset.away);
  });
}

function switchView(view) {
  state.view = view;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  if (view === "fixtures") loadFixtures();
  if (view === "manual") loadManual();
  if (view === "league") loadLeague();
  if (view === "sim") loadSimulation();
  if (view === "about") loadAbout();
}

function selectLeague(id) {
  if (state.league === id) return;
  state.league = id;
  renderChips();
  state.teams = [];
  document.querySelectorAll("#view-manual select").forEach((s) => (s.innerHTML = ""));
  document.getElementById("manualResult").innerHTML = "";
  if (state.view === "fixtures") loadFixtures();
  if (state.view === "manual") loadManual();
  if (state.view === "league") loadLeague();
  if (state.view === "sim") loadSimulation();
}

function renderChips() {
  document.getElementById("leagueChips").innerHTML = state.leagues
    .map(
      (l) => `<button class="chip ${l.id === state.league ? "active" : ""}" data-league="${l.id}">
        <span>${l.flag}</span><span>${escapeHtml(l.name_fa)}</span>
      </button>`
    )
    .join("");
}

function renderMeta() {
  const meta = state.meta;
  if (!meta) return;
  document.getElementById("dataMeta").innerHTML = `<span class="dot"></span>
    <span>آخرین نتیجه در داده: ${formatDate(meta.data_through)}</span>`;
  document.getElementById("footerStat").textContent =
    `${fa(meta.matches.toLocaleString("en-US"))} بازی · ${fa(meta.teams)} تیم · ${fa(meta.leagues)} لیگ`;
}

/* ─────────────────────────── بازی‌های پیش‌رو ─────────────────────────── */

async function loadFixtures() {
  const grid = document.getElementById("fixturesGrid");
  grid.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>`;
  try {
    const data = await api("/api/fixtures", { league: state.league, limit: 24 });
    if (!data.fixtures.length) {
      grid.innerHTML = `<div class="panel">بازی پیش‌رویی برای این لیگ ثبت نشده است.</div>`;
      return;
    }
    grid.innerHTML = data.fixtures.map((f, i) => fixtureCard(f, i)).join("");
  } catch (err) {
    grid.innerHTML = errorBox(err.message);
  }
}

function confidence(p) {
  const top = Math.max(p.prob_home, p.prob_draw, p.prob_away);
  if (top >= 0.6) return { label: "اطمینان بالا", low: false };
  if (top >= 0.45) return { label: "اطمینان متوسط", low: false };
  return { label: "بازی نزدیک", low: true };
}

function fixtureCard(f, i = 0) {
  const conf = confidence(f);
  const score = f.most_likely_score;
  return `<article class="match-card" data-home="${f.home}" data-away="${f.away}" style="animation-delay:${Math.min(i * 0.03, 0.4)}s">
    <div class="match-top">
      <span class="match-date">📅 ${formatDate(f.date)}</span>
      <span class="confidence ${conf.low ? "low" : ""}">${conf.label}</span>
    </div>
    <div class="match-teams">
      <div class="team home">
        <span class="team-name">${escapeHtml(f.home_fa)}</span>
        <span class="team-xg">گل انتظاری ${num(f.expected_home_goals, 1)}</span>
      </div>
      <span class="score-chip">${fa(score[0])} - ${fa(score[1])}</span>
      <div class="team away">
        <span class="team-name">${escapeHtml(f.away_fa)}</span>
        <span class="team-xg">گل انتظاری ${num(f.expected_away_goals, 1)}</span>
      </div>
    </div>
    <div class="prob-bar">
      <span class="pbar-home" style="width:${(f.prob_home * 100).toFixed(1)}%"></span>
      <span class="pbar-draw" style="width:${(f.prob_draw * 100).toFixed(1)}%"></span>
      <span class="pbar-away" style="width:${(f.prob_away * 100).toFixed(1)}%"></span>
    </div>
    <div class="prob-labels">
      <span><span class="k">۱</span><b>${pct(f.prob_home)}</b></span>
      <span class="mid"><span class="k">X</span><b>${pct(f.prob_draw)}</b></span>
      <span class="end"><span class="k">۲</span><b>${pct(f.prob_away)}</b></span>
    </div>
    <div class="match-foot">
      <span class="tag">مجموع گل <b>${num(f.expected_home_goals + f.expected_away_goals, 1)}</b></span>
      <span class="tag">بالای ۲.۵ <b>${pct(f.over_under.over_2_5)}</b></span>
      <span class="tag">هر دو گل <b>${pct(f.btts)}</b></span>
    </div>
  </article>`;
}

/* ─────────────────────────── مودال جزئیات ─────────────────────────── */

async function openDetail(home, away) {
  const modal = document.getElementById("modal");
  const body = document.getElementById("modalBody");
  modal.classList.remove("hidden");
  body.innerHTML = `<div class="skeleton" style="height:320px"></div>`;
  try {
    const p = await api("/api/predict", { league: state.league, home, away });
    body.innerHTML = detailHtml(p);
  } catch (err) {
    body.innerHTML = errorBox(err.message);
  }
}

function closeModal() {
  document.getElementById("modal").classList.add("hidden");
}

function detailHtml(p) {
  const score = p.most_likely_score;
  const s = p.top_scores
    .map(
      (t) => `<div class="kv"><span>${fa(t.home)} - ${fa(t.away)}</span><b>${pct(t.prob)}</b></div>`
    )
    .join("");
  const ou = p.over_under;
  const markets = `
    <div class="kv"><span>بالای ۱.۵ گل</span><b>${pct(ou.over_1_5)}</b></div>
    <div class="kv"><span>بالای ۲.۵ گل</span><b>${pct(ou.over_2_5)}</b></div>
    <div class="kv"><span>بالای ۳.۵ گل</span><b>${pct(ou.over_3_5)}</b></div>
    <div class="kv"><span>هر دو گل می‌زنند</span><b>${pct(p.btts)}</b></div>`;
  const dc = `
    <div class="kv"><span>۱X (میزبان یا مساوی)</span><b>${pct(p.double_chance["1X"])}</b></div>
    <div class="kv"><span>۱۲ (بدون مساوی)</span><b>${pct(p.double_chance["12"])}</b></div>
    <div class="kv"><span>X۲ (میهمان یا مساوی)</span><b>${pct(p.double_chance["X2"])}</b></div>`;

  return `
  <div class="detail-head">
    <div>
      <div class="detail-team">${escapeHtml(p.home_fa)} <span style="color:var(--muted)">×</span> ${escapeHtml(p.away_fa)}</div>
      <div class="detail-sub">گل انتظاری ${num(p.expected_home_goals, 2)} - ${num(p.expected_away_goals, 2)}</div>
    </div>
    <div class="detail-score">${fa(score[0])} - ${fa(score[1])}</div>
  </div>
  <div class="big-probs">
    <div class="big-prob h"><div class="v">${pct(p.prob_home)}</div><div class="l">برد میزبان (۱)</div></div>
    <div class="big-prob d"><div class="v">${pct(p.prob_draw)}</div><div class="l">مساوی (X)</div></div>
    <div class="big-prob a"><div class="v">${pct(p.prob_away)}</div><div class="l">برد میهمان (۲)</div></div>
  </div>
  <div class="detail-grid">
    <div class="detail-block">
      <h3>بازار گل</h3>${markets}
      <h3 style="margin-top:14px">شانس دوگانه</h3>${dc}
    </div>
    <div class="detail-block">
      <h3>محتمل‌ترین نتایج</h3>${s}
    </div>
  </div>
  <div class="detail-block" style="margin-top:16px">
    <h3>ماتریس احتمال نتیجه (سطر: گل میزبان، ستون: گل میهمان)</h3>
    ${matrixHtml(p.matrix)}
  </div>`;
}

function matrixHtml(matrix) {
  if (!matrix || !matrix.length) return "";
  const size = matrix.length;
  const max = Math.max(...matrix.flat());
  const cells = [];
  cells.push(`<div class="mcell mhead"></div>`);
  for (let j = 0; j < size; j++) cells.push(`<div class="mcell mhead">${fa(j)}</div>`);
  for (let i = 0; i < size; i++) {
    cells.push(`<div class="mcell mhead">${fa(i)}</div>`);
    for (let j = 0; j < size; j++) {
      const p = matrix[i][j];
      const alpha = Math.pow(p / max, 0.65);
      cells.push(
        `<div class="mcell" title="${fa(i)}-${fa(j)}: ${pct(p)}"
          style="background:rgba(0,224,138,${(alpha * 0.85).toFixed(3)});color:${alpha > 0.55 ? "#04120c" : "rgba(255,255,255,.55)"}">
          ${(p * 100).toFixed(1).replace(/\d/g, (d) => FA_DIGITS[+d])}
        </div>`
      );
    }
  }
  return `<div class="matrix" style="grid-template-columns:repeat(${size + 1}, 1fr)">${cells.join("")}</div>`;
}

/* ─────────────────────────── پیش‌بینی دستی ─────────────────────────── */

async function loadManual() {
  const homeSel = document.getElementById("homeSelect");
  const awaySel = document.getElementById("awaySelect");
  if (!state.teams.length) {
    try {
      const data = await api("/api/teams", { league: state.league });
      state.teams = data.teams;
      const options = state.teams
        .map((t) => `<option value="${t.id}">${escapeHtml(t.name)}</option>`)
        .join("");
      homeSel.innerHTML = options;
      awaySel.innerHTML = options;
      if (state.teams.length > 1) awaySel.selectedIndex = 1;
    } catch (err) {
      document.getElementById("manualResult").innerHTML = errorBox(err.message);
      return;
    }
  }
}

async function runManualPrediction() {
  const home = document.getElementById("homeSelect").value;
  const away = document.getElementById("awaySelect").value;
  const box = document.getElementById("manualResult");
  const btn = document.getElementById("predictBtn");
  if (!home || !away) return;
  if (home === away) {
    box.innerHTML = errorBox("تیم میزبان و میهمان نباید یکی باشند.");
    return;
  }
  btn.disabled = true;
  btn.textContent = "در حال محاسبه…";
  box.innerHTML = `<div class="panel" style="margin-top:16px"><div class="skeleton" style="height:240px"></div></div>`;
  try {
    const p = await api("/api/predict", { league: state.league, home, away });
    box.innerHTML = `<div class="panel" style="margin-top:16px">${detailHtml(p)}</div>`;
  } catch (err) {
    box.innerHTML = `<div class="panel" style="margin-top:16px">${errorBox(err.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "پیش‌بینی کن";
  }
}

/* ─────────────────────────── جدول و قدرت ─────────────────────────── */

async function loadLeague() {
  const tableEl = document.getElementById("leagueTable");
  const powerEl = document.getElementById("powerList");
  tableEl.innerHTML = `<div class="skeleton" style="height:300px"></div>`;
  powerEl.innerHTML = `<div class="skeleton" style="height:300px"></div>`;
  try {
    const [table, power] = await Promise.all([
      api("/api/table", { league: state.league }),
      api("/api/power", { league: state.league }),
    ]);
    tableEl.innerHTML = tableHtml(table.table);
    powerEl.innerHTML = powerHtml(power.power);
  } catch (err) {
    tableEl.innerHTML = errorBox(err.message);
  }
}

function tableHtml(rows) {
  if (!rows.length) return `<p class="hint">جدولی موجود نیست.</p>`;
  const total = rows.length;
  const body = rows
    .map((r) => {
      let zone = "";
      if (r.position === 1) zone = '<span class="zone zone-champ"></span>';
      else if (r.position <= 4) zone = '<span class="zone zone-euro"></span>';
      else if (r.position > total - 3) zone = '<span class="zone zone-drop"></span>';
      return `<tr>
        <td class="pos">${fa(r.position)}</td>
        <td class="team-cell">${zone}${escapeHtml(r.name)}</td>
        <td>${fa(r.played)}</td>
        <td>${fa(r.won)}</td>
        <td>${fa(r.drawn)}</td>
        <td>${fa(r.lost)}</td>
        <td>${fa(r.gf)}:${fa(r.ga)}</td>
        <td>${r.gd > 0 ? "+" : ""}${fa(r.gd)}</td>
        <td class="pts">${fa(r.points)}</td>
      </tr>`;
    })
    .join("");
  return `<table>
    <thead><tr>
      <th>#</th><th>تیم</th><th>بازی</th><th>برد</th><th>مساوی</th><th>باخت</th><th>گل</th><th>تفاضل</th><th>امتیاز</th>
    </tr></thead>
    <tbody>${body}</tbody>
  </table>`;
}

function powerHtml(rows) {
  if (!rows.length) return `<p class="hint">داده‌ای موجود نیست.</p>`;
  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.power)), 0.35);
  return rows
    .map((r) => {
      const width = (Math.abs(r.power) / maxAbs) * 50;
      const right = r.power >= 0 ? 50 : 50 - width;
      const color = r.power >= 0
        ? "linear-gradient(90deg,#059669,#00e08a)"
        : "linear-gradient(90deg,#ef4444,#f97316)";
      return `<div class="power-row">
        <span class="power-rank">${fa(r.rank)}</span>
        <span class="power-name">${escapeHtml(r.name)}</span>
        <span class="power-track">
          <span style="position:absolute;inset-block:0;right:50%;width:1px;background:rgba(255,255,255,.12)"></span>
          <span class="power-fill" style="right:${right}%;width:${width}%;background:${color}"></span>
        </span>
        <span class="power-val">${r.power > 0 ? "+" : ""}${num(r.power, 2)}</span>
      </div>`;
    })
    .join("");
}

/* ─────────────────────────── شبیه‌سازی ─────────────────────────── */

async function loadSimulation() {
  const box = document.getElementById("simTable");
  if (state.simCache[state.league]) {
    box.innerHTML = simHtml(state.simCache[state.league]);
    return;
  }
  box.innerHTML = `<div class="skeleton" style="height:320px"></div>`;
  try {
    const data = await api("/api/simulate", { league: state.league, runs: 1500 });
    state.simCache[state.league] = data.simulation;
    box.innerHTML = simHtml(data.simulation);
  } catch (err) {
    box.innerHTML = errorBox(err.message);
  }
}

function simHtml(rows) {
  if (!rows || !rows.length) return `<p class="hint">داده‌ای برای شبیه‌سازی نیست.</p>`;
  const body = rows
    .map(
      (r) => `<tr>
      <td class="pos">${fa(r.projected_rank)}</td>
      <td class="team-cell">${escapeHtml(r.name)}</td>
      <td>${fa(r.current_points)}</td>
      <td>${num(r.exp_points, 1)}</td>
      <td><div class="prob-bar" style="min-width:90px">
        <span class="pbar-home" style="width:${(r.title_prob * 100).toFixed(1)}%"></span>
        <span style="width:${(100 - r.title_prob * 100).toFixed(1)}%;background:rgba(255,255,255,.05)"></span>
      </div><span style="font-size:11.5px;color:var(--muted)">${pct0(r.title_prob)}</span></td>
      <td>${pct0(r.top5_prob)}</td>
      <td style="color:${r.relegation_prob > 0.4 ? "#f87171" : "inherit"}">${pct0(r.relegation_prob)}</td>
    </tr>`
    )
    .join("");
  return `<table>
    <thead><tr>
      <th>#</th><th>تیم</th><th>امتیاز فعلی</th><th>امتیاز پیش‌بینی</th><th>قهرمانی</th><th>پنجم یا بهتر</th><th>سقوط</th>
    </tr></thead>
    <tbody>${body}</tbody>
  </table>`;
}

/* ─────────────────────────── درباره مدل ─────────────────────────── */

async function loadAbout() {
  const stats = document.getElementById("backtestBox");
  const facts = document.getElementById("dataFacts");
  try {
    const meta = state.meta || (await api("/api/meta"));
    state.meta = meta;
    const bt = meta.backtest && meta.backtest.summary;
    if (bt) {
      stats.innerHTML = `
        <div class="stat"><div class="v">${pct(bt.accuracy)}</div><div class="l">دقت پیش‌بینی (۱X۲)</div></div>
        <div class="stat"><div class="v">${num(bt.logloss, 3)}</div><div class="l">Log-loss (کمتر بهتر)</div></div>
        <div class="stat"><div class="v">${num(bt.brier, 3)}</div><div class="l">امتیاز بریر</div></div>
        <div class="stat"><div class="v">${fa(bt.matches.toLocaleString("en-US"))}</div><div class="l">بازی آزمایش‌شده</div></div>
        <div class="stat"><div class="v">${pct(bt.baseline_accuracy)}</div><div class="l">دقت مدل ساده (همیشه میزبان)</div></div>
        <div class="stat"><div class="v">${num(bt.baseline_logloss, 3)}</div><div class="l">Log-loss مدل ساده</div></div>`;
    } else {
      stats.innerHTML = `<p class="hint">فایل اعتبارسنجی موجود نیست. با اجرای <span class="mono">python3 scripts/backtest.py</span> ساخته می‌شود.</p>`;
    }
    facts.innerHTML = `
      <li><span>تعداد بازی‌های تاریخی</span><b>${fa(meta.matches.toLocaleString("en-US"))}</b></li>
      <li><span>تعداد تیم‌ها</span><b>${fa(meta.teams)}</b></li>
      <li><span>لیگ‌ها</span><b>${fa(meta.leagues)}</b></li>
      <li><span>آخرین نتیجه در داده</span><b>${formatDate(meta.data_through)}</b></li>
      <li><span>نیمه‌عمر وزن‌دهی زمانی</span><b>${fa(365)} روز</b></li>`;
  } catch (err) {
    stats.innerHTML = errorBox(err.message);
  }
}

init();
