// OBS overlay
(() => {
  "use strict";
  const params = new URLSearchParams(location.search);
  if (window.parent !== window) window.parent.postMessage("mkw-overlay-ready", "*");
  const root = document.getElementById("overlay");
  const fixedScale = parseFloat(params.get("scale"));

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  const floor3 = (x) => Math.floor(x * 1000) / 1000;   // do NOTTT round up

  function fit() {
    root.style.transform = "none";
    root.style.left = "0px";
    const bar = root.querySelector(".bar");
    if (bar) bar.style.width = "";
    if (fixedScale > 0) {
      root.style.transform = `scale(${fixedScale})`;
      return;
    }
    if (!bar) {
      const { width: w, height: h } = root.getBoundingClientRect();
      if (w && h) root.style.transform = `scale(${floor3(Math.min(innerWidth / w, innerHeight / h))})`;
      return;
    }
    // bar
    const widthWith = (mode) => {
      bar.classList.add(mode);
      const w = bar.getBoundingClientRect().width;
      bar.classList.remove(mode);
      return w;
    };
    const narrow = widthWith("narrowest"), wide = widthWith("widest");
    const rootBox = root.getBoundingClientRect();
    const frame = rootBox.width - bar.getBoundingClientRect().width;   // pad
    const s = floor3(Math.min(innerHeight / rootBox.height, innerWidth / (narrow + frame)));
    const width = Math.min(Math.max(innerWidth / s - frame, narrow), wide);
    bar.style.width = `${width}px`;
    root.style.left = `${Math.max(0, (innerWidth - (width + frame) * s) / 2)}px`;
    root.style.transform = `scale(${s})`;
  }

  function shrinkTags() {
    const range = document.createRange();
    const scale = root.getBoundingClientRect().width / root.offsetWidth || 1;
    for (const tag of root.querySelectorAll(".bar .tag, .list .tag")) {
      tag.style.fontSize = "";
      const style = getComputedStyle(tag);
      const room = tag.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      let size = parseFloat(style.fontSize);
      range.selectNodeContents(tag);
      while (range.getBoundingClientRect().width / scale > room && size > 13) tag.style.fontSize = `${--size}px`;
    }
  }

  const SHUFFLE = { duration: 520, easing: "cubic-bezier(.2,.8,.2,1)" };
  const PAGE = 8, PAGE_SECONDS = 5;   // FFA bar: full names need room, so at most 8 at a time (12p: 6 + 6)
  const FLIP = { duration: 420, easing: "cubic-bezier(.2,.8,.2,1)", fill: "backwards" };
  let last = null, pageTimer = null, shownPage = null;

  function places() {
    return new Map([...root.querySelectorAll(".cell[data-key]")].map((c) => [c.dataset.key, [c.offsetLeft, c.offsetTop]]));
  }

  function shuffle(before) {
    let moved = false;
    for (const cell of root.querySelectorAll(".cell[data-key]")) {
      const was = before.get(cell.dataset.key);
      if (!was) continue;
      const dx = was[0] - cell.offsetLeft, dy = was[1] - cell.offsetTop;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue;
      moved = true;
      cell.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], SHUFFLE);
    }
    if (moved) {
      for (const gap of root.querySelectorAll(".diff, .seam")) {
        gap.animate([{ opacity: 0 }, { opacity: 0, offset: 0.7 }, { opacity: 1 }], SHUFFLE);
      }
    }
  }

  function draw(state) {
    last = state;
    const before = places();
    const layout = params.get("layout") || state.settings.overlay_layout;
    const ffa = state.format === "FFA";
    let teams = state.teams;
    if (!teams.length) {
      // no capture yet
      const count = ffa ? Math.min(state.lobby, 12) : Math.max(2, state.lobby / (parseInt(state.format, 10) || 4));
      teams = Array.from({ length: count }, (_, i) => ({ tag: "–", short: "–", total: 0, rank: i + 1, gap: i ? 0 : null, mine: false }));
    }
    clearTimeout(pageTimer);
    let flipped = false;
    if (ffa && layout !== "list" && teams.length > PAGE) {
      const pages = Math.ceil(teams.length / PAGE), size = Math.ceil(teams.length / pages);
      const page = Math.floor(Date.now() / (PAGE_SECONDS * 1000)) % pages;
      flipped = shownPage !== null && page !== shownPage;
      shownPage = page;
      teams = teams.slice(page * size, page * size + size).map((t, i) => (i ? t : { ...t, gap: null }));
      pageTimer = setTimeout(() => draw(last), PAGE_SECONDS * 1000 - (Date.now() % (PAGE_SECONDS * 1000)));
    }
    const box = el("div", (layout === "list" ? "list" : "bar") + (ffa ? " ffa" : ""));
    teams.forEach((t, i) => {
      const diff = i && t.gap !== null ? `+${t.gap}` : null;
      const cell = el("div", "cell" + (t.mine ? " mine" : ""));
      if (t.key) cell.dataset.key = t.key;
      if (layout === "list") {
        cell.append(el("span", "rank r" + t.rank, t.rank), el("span", "tag", t.short || t.tag), el("span", "score", t.total));
        if (diff) cell.append(el("span", "seam", diff));
      } else {
        if (diff) box.append(el("span", "diff", diff));
        const tag = el("span", "tag", t.short || t.tag);
        if (ffa) tag.prepend(el("span", "pos", t.rank));
        cell.append(tag, el("span", "score", t.total));
      }
      box.append(cell);
    });
    const end = el("div", "end");
    const r = state.race;
    if (r.delta) end.append(el("span", "missing", (r.delta < 0 ? "−" : "+") + Math.abs(r.delta)));
    end.append(el("span", "left", `@${r.left}`));
    box.append(end);
    root.style.transform = "none";
    root.replaceChildren(box);
    fit();
    shrinkTags();
    if (flipped) {        // next page: the players swipe in from the right, one after another
      box.querySelectorAll(".cell, .diff").forEach((node, i) => node.animate(
        [{ opacity: 0, transform: "translateX(36px)" }, { opacity: 1, transform: "none" }], { ...FLIP, delay: i * 22 }));
    } else {
      shuffle(before);
    }
  }

  function connect() {
    if (params.has("once")) {
      fetch("/api/state").then((r) => r.json()).then(draw);
      return;
    }
    const stream = new EventSource("/api/events");
    stream.onmessage = (e) => draw(JSON.parse(e.data));
    stream.onerror = () => { stream.close(); setTimeout(reconnect, 3000); };
  }

  // OBS keeps this page open across app restarts: after one (or an update) reload, so the overlay runs the new code
  let run = null;
  const ping = () => fetch("/api/ping", { cache: "no-store" }).then((r) => r.json()).then((p) => p.run);
  function reconnect() {
    ping().then((now) => {
      if (run && now !== run) location.reload();
      else connect();
    }).catch(() => setTimeout(reconnect, 3000));
  }
  addEventListener("resize", () => { fit(); shrinkTags(); });
  Promise.all(["italic 20px MKRace", "20px MKFallback", "20px MKScore"].map((f) => document.fonts.load(f, "A1★")))
    .catch(() => {}).then(() => ping().then((now) => { run = now; }).catch(() => {})).then(connect);
})();
