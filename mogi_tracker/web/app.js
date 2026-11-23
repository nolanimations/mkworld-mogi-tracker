// MKWorld Mogi Tracker app window
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const token = window.MKW_TOKEN;
  let state = null;
  let selectedKey = null;       // clicked team row
  let lastMessageId = -1;
  let fadeTimer = null;
  let pendingCreate = null;     // {tag, points} waiting for "create this team?"
  let laterUpdate = null;
  let captureHover = false;
  let editingTag = null;        // key of the team whose tag is being edited (the board waits with redrawing)
  const TAG_MAX = 10;           // session.CUSTOM_TAG_MAX
  const PENCIL = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path fill="currentColor" d="M3 17.25V21h3.75L17.8 9.94l-3.75-3.75L3 17.25zm17.7-10.2a1 1 0 0 0 0-1.42l-2.33-2.33a1 1 0 0 0-1.42 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>';   // the version the user said "Later" to

  const KEY_NAMES = { down: "↓", up: "↑", left: "←", right: "→", space: "Space", enter: "Enter" };
  const prettyKey = (combo) => combo.split("+").map((k) => KEY_NAMES[k] || k).join(" + ");

  async function post(action, data = {}) {
    try {
      const r = await fetch("/api/" + action, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Token": token },
        body: JSON.stringify(data),
      });
      return await r.json();
    } catch (e) {
      return { ok: false, error: String(e) };
    }
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  // segmented controls
  function drawSeg(id, options, current, onPick) {
    const box = $(id);
    box.replaceChildren(...options.map(([value, label]) => {
      const b = el("button", "", label);
      b.type = "button";
      b.setAttribute("aria-pressed", String(value === current));
      b.addEventListener("click", () => value !== current && onPick(value));
      return b;
    }));
  }

  // race bar
  function drawRace() {
    const r = state.race;
    $("race-num").textContent = r.number || "–";
    $("race-of").textContent = `/${r.of}`;
    $("races-num").textContent = r.of;
    $("races-down").disabled = r.of <= 1;
    $("races-up").disabled = r.of >= 32;
    const flags = $("flags");
    if (flags.children.length !== r.of) flags.replaceChildren(...Array.from({ length: r.of }, () => el("i")));
    [...flags.children].forEach((f, i) => f.classList.toggle("done", i < r.number));
    const note = $("race-note");
    note.hidden = r.delta === 0;
    if (r.delta) {
      const n = Math.abs(r.delta);
      note.textContent = `${n} point${n === 1 ? "" : "s"} ${r.delta < 0 ? "missing" : "too many"}`;
    }
  }

  function drawMessage() {
    const m = state.message, box = $("message");
    if (m.id === lastMessageId) return;
    lastMessageId = m.id;
    box.textContent = m.text;
    box.className = "message " + (m.tone === "info" ? "" : m.tone);
    clearTimeout(fadeTimer);
    if (m.text) fadeTimer = setTimeout(() => box.classList.add("fade"), m.tone === "bad" ? 14000 : 8000);
  }

  // notices
  function drawNotices() {
    const items = [];
    if (state.updated) {
      const n = el("div", "notice note");
      n.append(el("p", "", `Succesfully updated to${state.version}`));
      const log = el("button", "pill-btn gold", "See changelog");
      log.addEventListener("click", () => post("changelog"));
      const ok = el("button", "pill-btn ghost", "OK");
      ok.addEventListener("click", () => post("dismiss_updated"));
      n.append(log, ok);
      items.push(n);
    }
    const up = state.update;
    if (up && laterUpdate !== up.version) {
      const n = el("div", "notice note");
      n.append(el("p", "", `Version ${up.version} is out (you have ${state.version})`));
      const go = el("button", "pill-btn gold", up.updating ? "Updating..." : up.auto ? "Update" : "Download");
      go.disabled = up.updating;
      go.addEventListener("click", () => post("update"));
      const later = el("button", "pill-btn ghost", "Later");
      later.hidden = up.updating;
      later.addEventListener("click", () => { laterUpdate = up.version; drawNotices(); });
      n.append(go, later);
      items.push(n);
    }
    if (pendingCreate) {
      const n = el("div", "notice");
      n.append(el("p", "", `No team with the tag “${pendingCreate.tag}” yet. Create it with ${pendingCreate.points > 0 ? "+" : ""}${pendingCreate.points} points?`));
      const yes = el("button", "pill-btn gold", "Create team");
      yes.addEventListener("click", async () => {
        const p = pendingCreate;
        pendingCreate = null;
        const out = await post("adjust", { tag: p.tag, points: p.points, create: true });
        if (out.ok) clearAdjust();
      });
      const no = el("button", "pill-btn ghost", "Cancel");
      no.addEventListener("click", () => { pendingCreate = null; drawNotices(); });
      n.append(yes, no);
      items.push(n);
    }
    if (state.format_hint) {
      const n = el("div", "notice");
      n.append(el("p", "", `This looks like a ${state.format_hint} mogi, but ${state.format} is selected.`));
      const b = el("button", "pill-btn gold", `Switch to ${state.format_hint}`);
      b.addEventListener("click", () => post("settings", { format: state.format_hint }));
      n.append(b);
      items.push(n);
    }
    for (const s of state.suggestions) {
      const n = el("div", "notice" + (s.button ? "" : " note"));
      n.append(el("p", "", s.text));
      if (s.button) {
        const yes = el("button", "pill-btn gold", s.button);
        yes.addEventListener("click", () => post("suggestion", { id: s.id, apply: true }));
        n.append(yes);
      }
      // a note says what the app already did by itself, there is nothing to apply
      const no = el("button", "pill-btn ghost", s.button ? "Dismiss" : "OK");
      no.addEventListener("click", () => post("suggestion", { id: s.id, apply: false }));
      n.append(no);
      items.push(n);
    }
    $("notices").replaceChildren(...items);
  }

  // --- board ---
  const TREND = {
    up: '<svg viewBox="0 0 26 26"><path d="M13 3 23 15h-6v8h-8v-8H3z" fill="#ff8a1e" stroke="#1d1613" stroke-width="2.4" stroke-linejoin="round"/></svg>',
    down: '<svg viewBox="0 0 26 26"><path d="M13 23 3 11h6V3h8v8h6z" fill="#2e9bff" stroke="#1d1613" stroke-width="2.4" stroke-linejoin="round"/></svg>',
    same: '<svg viewBox="0 0 26 26"><rect x="4" y="10" width="18" height="6.500" rx="2" fill="#5fd13c" stroke="#1d1613" stroke-width="2.4"/></svg>',
  };

  function drawBoard() {
    const board = $("board");
    if (editingTag && state.teams.some((t) => t.key === editingTag)) return;   // redrawn when the edit ends
    const before = new Map([...board.querySelectorAll(".row")].map((r) => [r.dataset.key, r.getBoundingClientRect().top]));
    if (!state.teams.some((t) => t.key === selectedKey)) selectedKey = null;
    board.classList.toggle("dense", state.teams.length > 8);

    if (!state.teams.length) {
      const empty = el("div", "empty");
      empty.append(el("div", "empty-title", "READY TO RACE"));
      const key = state.hotkey.combo ? ` or press ${prettyKey(state.hotkey.combo)}` : "";
      empty.append(el("p", "", state.settings.auto_capture
        ? "Auto-capture is on, please give the game time to show all the results!"
        : state.lobby === 12
          ? `Hit Capture${key} once the scoreboard finishes adding points`
          : `Hit Capture${key} the moment the scoreboard starts moving`));
      board.replaceChildren(empty);
      return;
    }

    board.replaceChildren(...state.teams.map((t) => {
      const row = el("div", "row" + (t.mine ? " mine" : "") + (t.key === selectedKey ? " selected" : ""));
      row.dataset.key = t.key;
      const trend = el("span", "trend");
      if (t.trend) trend.innerHTML = TREND[t.trend];   // markup fix
      const who = el("div", "who");
      const tag = el("span", "tag", t.tag);
      if (t.custom) tag.title = `Read as ${t.read}`;
      const pen = el("button", "tag-pen");
      pen.type = "button";
      pen.title = "Edit tag";
      pen.innerHTML = PENCIL;
      pen.addEventListener("click", (e) => { e.stopPropagation(); editTag(t, tag, pen); });
      const line = el("div", "tag-line");
      line.append(tag, pen);
      who.append(line);
      const members = el("span", "members");
      if (t.bank) members.append(el("span", "bank-chip", `bank ${t.bank > 0 ? "+" : ""}${t.bank}`));
      const shown = state.settings.player_points ? [...t.members].sort((a, b) => b.total - a.total) : t.members;
      shown.forEach((m, i) => {
        if (state.format === "FFA") {           // the row is the player: only say when they were read differently
          if (m.name !== t.tag) members.append(`read as ${m.name}`);
          return;
        }
        if (i) members.append(", ");
        members.append(m.name);
        if (state.settings.player_points) members.append(" ", el("b", "pp", m.total));
      });
      who.append(members);
      const points = el("div", "points");
      points.append(el("span", "total", t.total));
      row.append(trend, el("span", "rank r" + t.rank, t.rank), who,
                 el("span", "gain", t.gain > 0 ? `+${t.gain}` : ""), points);
      if (t.gap !== null) {
        const seam = el("span", "seam", `±${t.gap}`);
        seam.title = `${t.gap} point${t.gap === 1 ? "" : "s"} behind ${state.teams[state.teams.indexOf(t) - 1].tag}`;
        row.append(seam);
      }
      row.addEventListener("click", () => {
        if (String(window.getSelection())) return;
        selectTeam(t.key === selectedKey ? null : t);
      });
      return row;
    }));

    // row gliding
    for (const row of board.querySelectorAll(".row")) {
      const was = before.get(row.dataset.key);
      const dy = was === undefined ? 0 : was - row.getBoundingClientRect().top;
      if (dy) row.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], { duration: 320, easing: "cubic-bezier(.2,.8,.2,1)" });
    }
  }

  // Custom tags are only cosmetic. Saving any text makes it the team's tag, also the read tag typed again (that one
  // is often shown shortened, "V" for "V$"); only an empty box goes back to the read tag
  function editTag(t, tag, pen) {
    editingTag = t.key;
    const input = el("input", "input tag-input");
    input.type = "text";
    input.maxLength = TAG_MAX;
    input.spellcheck = false;
    input.value = t.tag;
    input.setAttribute("aria-label", `Tag for ${t.tag}`);
    tag.replaceWith(input);
    pen.hidden = true;
    input.focus();
    input.select();
    let typed = false, done = false;
    const finish = (save) => {
      if (done) return;
      done = true;
      editingTag = null;
      if (save) post("custom_tag", { key: t.key, tag: input.value });
      else drawBoard();
    };
    input.addEventListener("input", () => { typed = true; });
    input.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") finish(true);
      else if (e.key === "Escape") finish(false);
    });
    input.addEventListener("blur", () => finish(typed));   // clicking away keeps what was typed, an untouched box changes nothing
    input.addEventListener("click", (e) => e.stopPropagation());
  }

  function selectTeam(team) {
    selectedKey = team ? team.key : null;
    for (const row of document.querySelectorAll(".row")) row.classList.toggle("selected", row.dataset.key === selectedKey);
    if (team) {
      $("adj-tag").value = team.tag;
      $("adj-points").focus();
    }
  }

  function clearAdjust() {
    $("adj-tag").value = "";
    $("adj-points").value = "";
    selectTeam(null);
  }

  // dock
  function drawDock() {
    $("adj-tag").placeholder = state.format === "FFA" ? "Name" : "Tag";
    const busy = state.busy, btn = $("btn-capture");
    btn.classList.toggle("reading", busy);       // while reading, a click cancels
    btn.disabled = state.cancelling;
    btn.title = busy && !state.cancelling ? "Cancel this capture" : "";
    $("capture-label").textContent = state.cancelling ? "STOPPING" : busy ? (captureHover ? "CANCEL?" : "READING") : "CAPTURE";
    const cap = $("capture-key");
    cap.hidden = busy || !state.hotkey.combo;
    cap.textContent = prettyKey(state.hotkey.combo);
    const undo = $("btn-undo");
    undo.disabled = !state.undo || busy;
    undo.textContent = state.undo ? `Undo ${state.undo}` : "Undo";
    for (const id of ["btn-bank", "btn-reset"]) $(id).disabled = busy;
    const chip = $("auto-chip"), w = state.watching;
    chip.hidden = !w.on;
    chip.classList.toggle("bad", Boolean(w.error));
    chip.title = w.error || "Auto-capture is watching for the scoreboard";
  }

  function confirmButton(id, armedText, action) {
    const btn = $(id), text = btn.textContent;
    let timer = null;
    const disarm = () => { btn.classList.remove("armed"); btn.textContent = text; timer = null; };
    btn.addEventListener("click", () => {
      if (timer) { clearTimeout(timer); disarm(); action(); return; }
      btn.classList.add("armed");
      btn.textContent = armedText;
      timer = setTimeout(disarm, 4000);
    });
  }

  // the overlay fills a browser source of this size whatever the room size and format (see overlay.js)
  const OVERLAY_SIZE = { bar: "1920 × 120", list: "240 × 1080" };

  // settings drawer
  let monitors = [];
  function drawSettings() {
    const s = state.settings;
    drawSeg("seg-source", [["monitor", "Screen"], ["obs", "OBS Virtual Camera"]], s.source, (v) => post("settings", { source: v }));
    const mon = $("seg-monitor");
    mon.hidden = s.source !== "monitor" || monitors.length < 2;
    if (!mon.hidden) {
      drawSeg("seg-monitor", monitors.map((m) => [m.index, `${m.index}  (${m.width}×${m.height})`]), s.monitor, (v) => post("settings", { monitor: v }));
    }
    $("source-hint").textContent = s.source === "obs"
      ? "Press Start Virtual Camera in OBS first"
      : "Game should always be fullscreen";

    const hk = state.hotkey;
    $("hotkey-cap").textContent = hk.recording ? "…" : hk.combo ? prettyKey(hk.combo) : "none";
    $("btn-hotkey").textContent = hk.recording ? "Press a key (Esc for none)" : "Change";
    $("btn-hotkey").disabled = hk.recording;
    $("btn-hotkey-clear").hidden = hk.recording || !hk.combo;

    if (document.activeElement !== $("my-tag")) $("my-tag").value = s.my_tag;
    $("mark-my-tag").checked = s.mark_my_tag;
    $("auto-copy").checked = s.auto_copy;
    $("auto-accept").checked = s.auto_accept;
    $("player-points").checked = s.player_points;
    $("auto-capture").checked = s.auto_capture;
    drawSeg("seg-overlay", [["bar", "Bar"], ["list", "List"]], s.overlay_layout, (v) => post("settings", { overlay_layout: v }));
    $("overlay-url").value = state.overlay_url;
    $("overlay-file").value = state.overlay_file;
    $("overlay-size").textContent = `Source size: ${OVERLAY_SIZE[s.overlay_layout]}`;
    drawSeg("seg-background", [["dark", "Dark"], ["blue", "Blue"], ["light", "Light"]], s.background, (v) => post("settings", { background: v }));
    $("credits").textContent = `MKWorld Mogi Tracker ${state.version}. Racers Delight font by @ImWhoreHay, M PLUS 1p by the M+ Project. Text recognition built on PaddleOCR (Apache License 2.0). Not affiliated with Nintendo.`;
  }

  function openDrawer(open) {
    $("drawer").hidden = !open;
    $("scrim").hidden = !open;
    if (open) post("monitors").then((out) => { monitors = out.monitors || []; if (state) drawSettings(); });
  }

  // draw
  function draw() {
    document.documentElement.dataset.bg = state.settings.background;
    drawSeg("seg-lobby", [[24, "24"], [12, "12"]], state.lobby, (v) => post("settings", { lobby: v }));
    drawSeg("seg-format", state.formats.map((f) => [f, f]), state.format, (v) => post("settings", { format: v }));
    drawRace();
    drawMessage();
    drawNotices();
    drawBoard();
    drawDock();
    drawSettings();
  }

  function connect() {
    if (new URLSearchParams(location.search).has("once")) {
      fetch("/api/state").then((r) => r.json()).then((st) => { state = st; draw(); });
      return;
    }
    const stream = new EventSource("/api/events");
    stream.onmessage = (e) => { state = JSON.parse(e.data); draw(); };
  }

  const fontsReady = () => Promise.all(["italic 20px MKRace", "20px MKFallback", "20px MKScore"]
    .map((f) => document.fonts.load(f, "A1★"))).catch(() => {});

  // wiring
  $("btn-capture").addEventListener("click", () => post(state.busy ? "cancel" : "capture"));
  for (const [type, on] of [["mouseenter", true], ["mouseleave", false]]) {
    $("btn-capture").addEventListener(type, () => { captureHover = on; if (state) drawDock(); });
  }
  $("btn-copy").addEventListener("click", async () => {
    const out = await post("copy");
    if (!out.ok) return;
    const b = $("btn-copy");
    b.textContent = "Copied";
    b.classList.add("done");
    setTimeout(() => { b.textContent = "Copy"; b.classList.remove("done"); }, 1600);
  });
  $("btn-undo").addEventListener("click", () => post("undo"));
  confirmButton("btn-bank", "Click again to bank", () => post("bank_all"));
  confirmButton("btn-reset", "Click again to clear", () => post("reset"));

  $("adjust").addEventListener("submit", async (e) => {
    e.preventDefault();
    const tag = $("adj-tag").value.trim(), points = $("adj-points").value.trim();
    if (!tag) { $("adj-tag").focus(); return; }
    if (!points) { $("adj-points").focus(); return; }
    const out = await post("adjust", { tag, points });
    if (out.ok) clearAdjust();
    else if (out.reason === "unknown" && out.tag) { pendingCreate = { tag: out.tag, points: parseInt(points, 10) }; drawNotices(); }
    else if (out.reason === "points") $("adj-points").select();
    else $("adj-tag").select();
  });
  $("adj-tag").addEventListener("input", () => { if (selectedKey) selectTeam(null); pendingCreate = null; });

  // While typing here, the global hotkey must not start a capture
  document.addEventListener("focusin", (e) => { if (e.target.matches("input[type=text]")) post("typing", { on: true }); });
  document.addEventListener("focusout", (e) => { if (e.target.matches("input[type=text]")) post("typing", { on: false }); });
  window.addEventListener("blur", () => post("typing", { on: false }));
  window.addEventListener("focus", () => { if (document.activeElement?.matches("input[type=text]")) post("typing", { on: true }); });

  $("btn-settings").addEventListener("click", () => openDrawer(true));
  $("btn-close").addEventListener("click", () => openDrawer(false));
  $("scrim").addEventListener("click", () => openDrawer(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !state?.hotkey.recording) openDrawer(false); });
  $("btn-hotkey").addEventListener("click", () => post("hotkey"));
  $("btn-hotkey-clear").addEventListener("click", () => post("hotkey", { clear: true }));
  $("my-tag").addEventListener("change", (e) => post("settings", { my_tag: e.target.value }));
  $("mark-my-tag").addEventListener("change", (e) => post("settings", { mark_my_tag: e.target.checked }));
  $("auto-accept").addEventListener("change", (e) => post("settings", { auto_accept: e.target.checked }));
  $("auto-copy").addEventListener("change", (e) => post("settings", { auto_copy: e.target.checked }));
  $("player-points").addEventListener("change", (e) => post("settings", { player_points: e.target.checked }));
  $("races-down").addEventListener("click", () => post("settings", { races: state.race.of - 1 }));
  $("races-up").addEventListener("click", () => post("settings", { races: state.race.of + 1 }));
  $("auto-capture").addEventListener("change", (e) => post("settings", { auto_capture: e.target.checked }));
  async function copyField(button, field) {
    $(field).select();
    try { await navigator.clipboard.writeText($(field).value); } catch { document.execCommand("copy"); }
    $(button).textContent = "Copied";
    setTimeout(() => { $(button).textContent = "Copy"; }, 1600);
  }
  $("btn-overlay-copy").addEventListener("click", () => copyField("btn-overlay-copy", "overlay-url"));
  $("btn-overlay-file-copy").addEventListener("click", () => copyField("btn-overlay-file-copy", "overlay-file"));
  $("btn-last").addEventListener("click", () => post("open_folder", { which: "last" }));
  $("btn-licences").addEventListener("click", () => post("open_licences"));

  fontsReady().then(connect);
})();
