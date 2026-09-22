"use strict";

const $ = (id) => document.getElementById(id);

const ui = {
  score: $("score"), scoreFill: $("scoreFill"), chest: $("chest"),
  combosDone: $("combosDone"), cardsLeft: $("cardsLeft"), combosPossible: $("combosPossible"),
  activeSlot: $("activeSlot"), target: $("target"), completions: $("completions"),
  btnComplete: $("btnComplete"), btnDraw: $("btnDraw"),
  hand: $("hand"), locked: $("locked"), lockedArea: $("lockedArea"),
  odds: $("odds"), oddsNote: $("oddsNote"), drawsPicker: $("drawsPicker"),
  entryPanel: $("entryPanel"), entryTitle: $("entryTitle"), picker: $("picker"),
  entryText: $("entryText"), staging: $("staging"),
  btnEntryAdd: $("btnEntryAdd"), btnEntryConfirm: $("btnEntryConfirm"),
  btnEntryClear: $("btnEntryClear"), btnNoMore: $("btnNoMore"),
  advicePanel: $("advicePanel"), btnAdvise: $("btnAdvise"), btnDeep: $("btnDeep"),
  adviceReason: $("adviceReason"), steps: $("steps"), adviceButtons: $("adviceButtons"),
  agentStatus: $("agentStatus"), agentMode: $("agentMode"),
  btnNew: $("btnNew"), btnUndo: $("btnUndo"),
  showHints: $("showHints"), hints: $("hints"),
  events: $("events"), stats: $("stats"), logTable: $("logTable"), scoring: $("scoring"),
};

let config = null;
let state = null;
let advice = null;
let staged = [];          // onaylanmayı bekleyen kartlar
let busy = false;
let draws = 3;            // olasılıklar kaç çekiş için gösterilsin
let dragIndex = null;     // sürüklenen elin kaçıncı kartı

const DRAW_CHOICES = [1, 3, 5, 10];
const SOURCE_LABEL = { llm: "LLM", solver: "SOLVER", human: "SEN" };
const COMBO_LABEL = {
  group: "Grup", run_same_color: "Seri (aynı renk)",
  run_mixed: "Seri (karışık)", invalid: "Geçersiz",
};

// ------------------------------------------------------------------ istekler

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}
const post = (path, body) => api(path, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

const label = (card) => `${card.rank}${(config.color_codes || {})[card.color] || card.color[0]}`;

// ------------------------------------------------------------- olasılık

/**
 * `pool` kartlık desteden `count` kart çekilince, `successes` adet aranan
 * karttan en az birinin gelme olasılığı (hipergeometrik).
 */
function chanceOfSeeing(successes, pool, count) {
  if (successes <= 0 || pool <= 0) return 0;
  const d = Math.min(count, pool);
  let none = 1;
  for (let i = 0; i < d; i++) {
    const left = pool - successes - i;
    if (left <= 0) return 1;
    none *= left / (pool - i);
  }
  return 1 - none;
}

const pct = (p) => `%${(p * 100).toFixed(p >= 0.095 ? 0 : 1)}`;

function unseenMap() {
  const map = new Map();
  (state.unseen || []).forEach((u) => map.set(`${u.rank}|${u.color}`, u.count));
  return map;
}

// --------------------------------------------------------------- kart cizim

function cardEl(card, extra = "") {
  const el = document.createElement("div");
  el.className = `card ${extra}`.trim();
  if (!card) { el.classList.add("empty"); return el; }
  el.dataset.color = card.color;
  el.textContent = card.rank;
  el.title = label(card);
  return el;
}

function renderActive() {
  ui.activeSlot.innerHTML = "";
  const slot = state.active_slot === null ? null : (state.slots || [])[state.active_slot];
  if (!slot) {
    ui.activeSlot.innerHTML = '<span class="muted">tüm üçlüler tamamlandı</span>';
    ui.target.textContent = "";
    ui.completions.innerHTML = "";
    return;
  }
  for (let i = 0; i < slot.capacity; i++) {
    const card = slot.cards[i] || null;
    const el = cardEl(card, "xl drop");
    if (card && !slot.is_locked) {
      el.title = `${label(card)} · geri almak için tıkla`;
      el.onclick = () => takeBack(i);
    } else if (!card) {
      bindDropTarget(el);
    }
    ui.activeSlot.appendChild(el);
  }
  ui.target.textContent = state.is_over ? "" : (state.target || "");
  renderFeltActions();
  renderCompletions();
}

// Elden üçlüye sürükleyip bırakma
function bindDropTarget(el) {
  el.ondragover = (event) => { event.preventDefault(); el.classList.add("over"); };
  el.ondragleave = () => el.classList.remove("over");
  el.ondrop = (event) => {
    event.preventDefault();
    el.classList.remove("over");
    if (dragIndex !== null) manualMove("place", dragIndex);
  };
}

// "Tamamla" ve "Kart Çek" düğmeleri: hangisi mümkünse o görünür
function renderFeltActions() {
  const combo = state.pending_combo;
  ui.btnComplete.classList.toggle("hidden", !state.can_complete);
  if (state.can_complete) {
    const zero = !combo || !combo.points;
    ui.btnComplete.className = "btn big " + (zero ? "zero" : "ready");
    ui.btnComplete.textContent = zero
      ? "Tamamla (0 puan)"
      : `Tamamla · ${COMBO_LABEL[combo.kind] || ""} +${combo.points}`;
    ui.btnComplete.title = zero
      ? "Bu üçlü puan getirmiyor; istersen kart geri alıp değiştir."
      : combo.label;
  }

  const canDraw = !state.is_over && state.pending_draws === 0 && state.draw_count > 0;
  ui.btnDraw.classList.toggle("hidden", !canDraw);
  if (canDraw) {
    ui.btnDraw.className = "btn big" + (state.can_complete ? "" : " ready");
    ui.btnDraw.textContent = `Kart Çek (${state.draw_count})`;
  }
}

// "Bu üçlüyü hangi kart, kaç puana, hangi ihtimalle tamamlar"
function renderCompletions() {
  const rows = state.completions || [];
  ui.completions.innerHTML = "";
  if (!rows.length) return;

  rows.forEach((row) => {
    const chip = document.createElement("span");
    const chance = row.in_hand ? 1 : chanceOfSeeing(row.remaining, state.cards_left, draws);
    chip.className = "completion" + (row.in_hand ? " here" : (row.remaining ? "" : " gone"));
    chip.appendChild(cardEl(row, "tiny"));
    const info = document.createElement("span");
    info.innerHTML = `<b>+${row.points}</b> ` + (
      row.in_hand ? '<span class="odds-pct">elinde</span>'
        : row.remaining ? `<span class="odds-pct">${pct(chance)}</span>`
          : '<span class="odds-pct">kalmadı</span>');
    chip.appendChild(info);
    chip.title = row.in_hand
      ? "bu kart zaten elinde"
      : `destede ${row.remaining} adet · ${draws} çekişte gelme şansı ${pct(chance)}`;
    ui.completions.appendChild(chip);
  });
}

function renderHand() {
  ui.hand.innerHTML = "";
  const hand = state.hand || [];
  if (!hand.length) { ui.hand.innerHTML = '<span class="muted">—</span>'; return; }
  const first = advice && advice.steps ? advice.steps.find((x) => x.card) : null;
  const suggested = first ? label(first.card) : null;
  hand.forEach((card, index) => {
    const el = cardEl(card);
    if (label(card) === suggested) el.classList.add("suggested");
    el.title = `${label(card)} · sol tık: açık üçlüye koy · sağ tık: yok et`;
    el.onclick = () => manualMove("place", index);
    el.oncontextmenu = (event) => { event.preventDefault(); manualMove("discard", index); };
    el.draggable = true;
    el.ondragstart = () => {
      dragIndex = index;
      el.classList.add("drag");
      ui.activeSlot.classList.add("dragging");
    };
    el.ondragend = () => {
      dragIndex = null;
      el.classList.remove("drag");
      ui.activeSlot.classList.remove("dragging");
    };
    ui.hand.appendChild(el);
  });
}

function renderLocked() {
  const done = (state.slots || []).filter((s) => s.is_full);
  ui.lockedArea.classList.toggle("hidden", !done.length);
  ui.locked.innerHTML = "";
  done.forEach((slot) => {
    const row = document.createElement("div");
    row.className = "locked-row" + (slot.result && slot.result.points ? "" : " zero");
    const cards = document.createElement("div");
    cards.className = "locked-cards";
    slot.cards.forEach((c) => cards.appendChild(cardEl(c, "small")));
    const pts = document.createElement("span");
    pts.className = "locked-points";
    pts.textContent = slot.result ? slot.result.points : "";
    row.append(cards, pts);
    row.title = slot.result ? slot.result.label : "";
    ui.locked.appendChild(row);
  });
}

function renderScore() {
  ui.score.textContent = state.total_score;
  const max = config.max_score || 1;
  ui.scoreFill.style.width = `${Math.min(100, (state.total_score / max) * 100)}%`;
  ui.combosDone.textContent = state.combos_done;
  ui.cardsLeft.textContent = state.cards_left;
  ui.combosPossible.textContent = state.combos_possible;
  const chest = state.chest || {};
  ui.chest.innerHTML =
    `<span class="chest-icon" data-chest="${chest.chest || "bronze"}"></span>
     <span>${escapeHtml(chest.label || "")}</span>`;
}

// --------------------------------------------------- destede kalanlar

function renderDrawsPicker() {
  ui.drawsPicker.innerHTML = "";
  DRAW_CHOICES.forEach((n) => {
    const b = document.createElement("button");
    b.textContent = `${n} çekiş`;
    if (n === draws) b.classList.add("on");
    b.onclick = () => { draws = n; render(); };
    ui.drawsPicker.appendChild(b);
  });
}

function renderOdds() {
  const remaining = unseenMap();
  const pool = state.cards_left;
  const wanted = new Set((state.completions || [])
    .filter((c) => c.remaining > 0).map((c) => `${c.rank}|${c.color}`));

  ui.odds.innerHTML = "";
  config.colors.forEach((color) => {
    const row = document.createElement("div");
    row.className = "odds-row";
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.dataset.color = color;
    row.appendChild(swatch);

    config.ranks.forEach((rank) => {
      const key = `${rank}|${color}`;
      const count = remaining.get(key) || 0;
      const cell = document.createElement("div");
      cell.className = "odds-cell" + (count ? "" : " gone") + (wanted.has(key) ? " wanted" : "");
      cell.appendChild(cardEl({ rank, color }, "tiny"));
      const p = document.createElement("span");
      p.className = "pct";
      p.textContent = count ? pct(chanceOfSeeing(count, pool, draws)) : "—";
      cell.appendChild(p);
      cell.title = count
        ? `${rank}${config.color_codes[color]} · destede ${count} adet · ${draws} çekişte ${p.textContent}`
        : `${rank}${config.color_codes[color]} · destede kalmadı`;
      row.appendChild(cell);
    });
    ui.odds.appendChild(row);
  });

  // sayı bazında toplam: "herhangi bir 6"
  const totals = document.createElement("div");
  totals.className = "odds-totals";
  totals.innerHTML = `<span>${draws} çekişte herhangi bir:</span>` + config.ranks.map((rank) => {
    const count = config.colors.reduce((n, c) => n + (remaining.get(`${rank}|${c}`) || 0), 0);
    return `<span>${rank} → <b>${count ? pct(chanceOfSeeing(count, pool, draws)) : "—"}</b></span>`;
  }).join("");
  ui.odds.appendChild(totals);

  // açık üçlünün tamamlanma şansı
  const live = (state.completions || []).filter((c) => c.remaining > 0 || c.in_hand);
  if (live.some((c) => c.in_hand)) {
    const best = live.filter((c) => c.in_hand).reduce((a, b) => (a.points >= b.points ? a : b));
    ui.oddsNote.innerHTML =
      `Üçlüyü <b>${label(best)}</b> ile şimdi kapatabilirsin: <b>+${best.points}</b> puan.`;
  } else if (live.length) {
    const successes = live.reduce((n, c) => n + c.remaining, 0);
    const best = live.reduce((a, b) => (a.points >= b.points ? a : b));
    ui.oddsNote.innerHTML =
      `Üçlüyü tamamlayacak ${successes} kart var — ${draws} çekişte gelme şansı ` +
      `<b>${pct(chanceOfSeeing(successes, pool, draws))}</b>, en iyisi ` +
      `<b>${label(best)}</b> (+${best.points}).`;
  } else if ((state.completions || []).length) {
    ui.oddsNote.innerHTML = "<b>Bu üçlü artık tamamlanamaz</b> — en değersiz kartlarla kapat.";
  } else {
    ui.oddsNote.textContent = "";
  }
}

// --------------------------------------------------------------- kart girisi

function renderPicker() {
  const remaining = unseenMap();
  staged.forEach((c) => {
    const key = `${c.rank}|${c.color}`;
    remaining.set(key, (remaining.get(key) || 0) - 1);
  });
  ui.picker.innerHTML = "";
  config.colors.forEach((color) => {
    const row = document.createElement("div");
    row.className = "picker-row";
    config.ranks.forEach((rank) => {
      const left = remaining.get(`${rank}|${color}`) || 0;
      const cell = cardEl({ rank, color }, "small");
      if (left <= 0) cell.classList.add("gone");
      cell.title = left > 0 ? `${rank}${config.color_codes[color]} · destede ${left}` : "kalmadı";
      cell.onclick = () => { if (left > 0) { staged.push({ rank, color }); renderEntry(); } };
      row.appendChild(cell);
    });
    ui.picker.appendChild(row);
  });
}

function renderEntry() {
  const pending = state.pending_draws || 0;
  ui.entryPanel.classList.toggle("hidden", pending === 0);
  if (pending === 0) { staged = []; return; }

  ui.entryTitle.textContent = state.move_no === 0
    ? `Oyundaki ilk ${pending} kartı gir`
    : `Yerine gelen ${pending} kartı gir`;

  if (staged.length > pending) staged.length = pending;
  ui.staging.innerHTML = "";
  staged.forEach((card, index) => {
    const el = cardEl(card, "small");
    el.title = "çıkarmak için tıkla";
    el.onclick = () => { staged.splice(index, 1); renderEntry(); };
    ui.staging.appendChild(el);
  });
  ui.btnEntryConfirm.disabled = staged.length === 0;
  ui.btnEntryConfirm.textContent = `Onayla (${staged.length}/${pending})`;
  renderPicker();
}

async function confirmEntry() {
  if (!staged.length) return;
  const result = await post("/api/cards", { cards: staged });
  if (result.error) { flash(result.error); return; }
  staged = [];
  setState(result);
}

async function addFromText() {
  const text = ui.entryText.value.trim();
  if (!text) return;
  const result = await post("/api/cards", { text });
  if (result.error) { flash(result.error); return; }
  ui.entryText.value = "";
  staged = [];
  setState(result);
}

// ------------------------------------------------------------------- oneri

function renderAdvice() {
  ui.steps.innerHTML = "";
  ui.adviceButtons.innerHTML = "";
  const blocked = !state || state.is_over || state.pending_draws > 0;
  ui.btnAdvise.disabled = blocked || busy;
  ui.btnDeep.disabled = blocked || busy;

  if (state.is_over) {
    ui.adviceReason.innerHTML =
      `<b>Tur bitti — ${state.total_score} puan, ${escapeHtml(state.chest.label)}.</b>`;
    return;
  }
  if (!advice || !advice.steps || !advice.steps.length) {
    ui.adviceReason.textContent = state.pending_draws ? "Önce gelen kartları gir." : "";
    return;
  }

  ui.adviceReason.innerHTML =
    `<span class="tag ${advice.source}">${SOURCE_LABEL[advice.source] || advice.source}</span>` +
    escapeHtml(advice.reason || "") +
    (advice.fallback_reason
      ? `<div class="muted small">model devre dışı: ${escapeHtml(advice.fallback_reason)}</div>`
      : "");

  advice.steps.forEach((step, index) => {
    const li = document.createElement("li");
    li.className = "step " + step.type;
    li.innerHTML = step.type === "complete"
      ? "<b>Tamamla</b> düğmesine bas"
      : step.type === "place"
        ? `<b>${escapeHtml(step.card_label)}</b> kartını <b>açık üçlüye koy</b>`
        : `<b>${escapeHtml(step.card_label)}</b> kartını <b>yok et</b>`;
    if (step.completes) {
      const gain = document.createElement("span");
      gain.className = "pts" + (step.points ? "" : " zero");
      gain.textContent = `üçlü tamamlanır: ${COMBO_LABEL[step.completes.kind] || ""} +${step.points}`;
      li.appendChild(gain);
    }
    if (index === 0) {
      const btn = document.createElement("button");
      btn.className = "btn mini";
      btn.textContent = "Yaptım";
      btn.onclick = () => applySteps(1);
      li.appendChild(btn);
    }
    ui.steps.appendChild(li);
  });

  if (advice.steps.length > 1) {
    const all = document.createElement("button");
    all.className = "btn";
    all.style.flex = "1 1 100%";
    all.textContent = `Hepsini yaptım (${advice.steps.length} adım)`;
    all.onclick = () => applySteps(advice.steps.length);
    ui.adviceButtons.appendChild(all);
  }
}

async function getAdvice() {
  await runAdvice(ui.btnAdvise, "Öneri Al", () => api("/api/advice?refresh=true"));
}
async function getDeepAdvice() {
  await runAdvice(ui.btnDeep, "Derin Analiz", () => post("/api/deep-advice"));
}

async function runAdvice(button, text, request) {
  if (busy) return;
  busy = true;
  button.textContent = "düşünüyor…";
  ui.btnAdvise.disabled = ui.btnDeep.disabled = true;
  try {
    const result = await request();
    advice = result.advice;
    if (result.error) flash(result.error);
    setState(result, true);
  } finally {
    busy = false;
    button.textContent = text;
    renderAdvice();
  }
}

async function applySteps(count) {
  const result = await post("/api/apply", { count });
  advice = result.advice || null;
  if (result.error && !result.applied) flash(result.error);
  setState(result, true);
}

async function manualMove(type, cardIndex) {
  const result = await post("/api/move", { type, card_index: cardIndex });
  if (result.error) { flash(result.error); return; }
  advice = null;
  setState(result, true);
}

async function completeCombo() {
  const result = await post("/api/complete");
  if (result.error) { flash(result.error); return; }
  advice = null;
  setState(result);
}

async function drawCards() {
  const result = await post("/api/draw");
  if (result.error) { flash(result.error); return; }
  advice = null;
  setState(result);
}

async function takeBack(position) {
  const result = await post("/api/take-back", { position });
  if (result.error) { flash(result.error); return; }
  advice = null;
  setState(result);
}

async function undo() {
  const result = await post("/api/undo");
  if (result.error) { flash(result.error); return; }
  advice = null;
  staged = [];
  setState(result, true);
}

// ------------------------------------------------------------------ yan bilgi

function renderEvents() {
  const events = (state.events || []).slice().reverse();
  ui.events.innerHTML = "";
  if (!events.length) { ui.events.innerHTML = '<li class="muted">Henüz hamle yok.</li>'; return; }
  events.forEach((event) => {
    const li = document.createElement("li");
    const who = SOURCE_LABEL[event.source] || event.source || "?";
    const what = event.action.type === "place"
      ? `${event.card_label} → üçlü` : `${event.card_label} yok edildi`;
    const gain = event.completed
      ? ` <span class="pts${event.points ? "" : " zero"}">${COMBO_LABEL[event.completed.kind] || ""} +${event.points}</span>`
      : "";
    li.innerHTML = `<span class="tag ${event.source}">${who}</span>#${event.move_no} ${escapeHtml(what)}${gain}`;
    ui.events.appendChild(li);
  });
}

async function renderHints() {
  if (!ui.showHints.checked || state.is_over || state.pending_draws > 0) {
    ui.hints.innerHTML = "";
    return;
  }
  try {
    const data = await api("/api/hints?top=4");
    ui.hints.innerHTML = data.hints.map((hint, index) => {
      const what = hint.action.type === "place"
        ? `${hint.card_label} → üçlü` : `${hint.card_label} at`;
      return `<li><b>${index + 1}.</b> ${escapeHtml(what)} <span class="muted small">${hint.value} · ${escapeHtml(hint.note || "")}</span></li>`;
    }).join("");
  } catch (err) {
    ui.hints.innerHTML = '<li class="muted">öneri alınamadı</li>';
  }
}

async function refreshLog() {
  try {
    const data = await api("/api/log?limit=10");
    const stats = data.stats || {};
    ui.stats.innerHTML = stats.games
      ? `<span>tur: <b>${stats.games}</b></span>
         <span>ortalama: <b>${stats.avg_score}</b></span>
         <span>en iyi: <b>${stats.best_score}</b></span>`
      : '<span class="muted">Henüz kayıtlı tur yok.</span>';
    ui.logTable.innerHTML =
      "<tr><th>tur</th><th>puan</th><th>sandık</th><th>üçlü</th><th>llm</th></tr>" +
      (data.games || []).map((row) => `<tr>
        <td>${escapeHtml(row.game_id)}</td><td><b>${escapeHtml(row.total_score)}</b></td>
        <td>${escapeHtml(row.chest)}</td><td>${escapeHtml(row.combos_done)}</td>
        <td>${escapeHtml(row.llm_moves || 0)}/${escapeHtml(row.moves)}</td></tr>`).join("");
  } catch (err) {
    ui.stats.innerHTML = '<span class="muted">log okunamadı</span>';
  }
}

async function refreshAgent() {
  try {
    const data = await api("/api/agent");
    ui.agentStatus.className = "status " + (data.ollama_up ? "up" : "down");
    ui.agentStatus.innerHTML = data.ollama_up
      ? `Ollama çalışıyor · <b>${escapeHtml(data.model)}</b> · aktif: ${escapeHtml(data.name)}`
      : "Ollama'ya ulaşılamıyor — önerileri solver verecek.";
  } catch (err) {
    ui.agentStatus.className = "status down";
    ui.agentStatus.textContent = "Agent durumu alınamadı.";
  }
}

function renderScoringTable() {
  const groups = { group: [], run_mixed: [], run_same_color: [] };
  config.scoring.forEach((row) => groups[row.kind].push(row));
  const section = (title, rows) =>
    `<div class="head">${title}</div>` +
    rows.map((r) => `<div><span>${r.pattern}</span><b>${r.points}</b></div>`).join("");
  ui.scoring.innerHTML =
    section("Grup", groups.group) +
    section("Seri · karışık", groups.run_mixed) +
    section("Seri · aynı renk", groups.run_same_color) +
    '<div class="head">Ödül</div>' +
    config.rewards.map((r) => `<div><span>${r.min_score}+</span><b>${escapeHtml(r.label)}</b></div>`).join("");
}

// -------------------------------------------------------------------- ortak

let flashTimer = null;
function flash(message) {
  ui.agentStatus.className = "status warn";
  ui.agentStatus.textContent = message;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => refreshAgent(), 4000);
}

function setState(payload, keepAdvice) {
  state = payload.state || payload;
  if (!keepAdvice && !state.has_advice) advice = null;
  render();
  if (state.is_over) refreshLog();
}

function render() {
  if (!state || state.phase === "none") return;
  renderScore();
  renderActive();
  renderHand();
  renderLocked();
  renderDrawsPicker();
  renderOdds();
  renderEntry();
  renderAdvice();
  renderEvents();
  renderHints();
  ui.btnUndo.disabled = !state.can_undo;
}

async function newGame() {
  advice = null;
  staged = [];
  setState(await post("/api/new", { agent_mode: ui.agentMode.value }));
  refreshAgent();
}

// --------------------------------------------------------------------- giris

async function init() {
  config = await api("/api/config");
  ui.agentMode.value = config.agent_mode;
  renderScoringTable();

  ui.btnNew.onclick = newGame;
  ui.btnUndo.onclick = undo;
  ui.btnComplete.onclick = completeCombo;
  ui.btnDraw.onclick = drawCards;
  ui.btnAdvise.onclick = getAdvice;
  ui.btnDeep.onclick = getDeepAdvice;
  ui.btnEntryAdd.onclick = addFromText;
  ui.btnEntryConfirm.onclick = confirmEntry;
  ui.btnEntryClear.onclick = () => { staged = []; renderEntry(); };
  ui.btnNoMore.onclick = async () => setState(await post("/api/no-more-cards"));
  ui.entryText.onkeydown = (event) => { if (event.key === "Enter") addFromText(); };
  ui.showHints.onchange = render;
  ui.agentMode.onchange = newGame;

  await refreshAgent();
  await refreshLog();
  const current = await api("/api/state");
  if (!current || current.phase === "none") await newGame();
  else setState(current);
}

init();
