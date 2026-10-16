/* Homepage: byline, dashboard cards and their mini charts (plain SVG, no Plotly). */
(() => {
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const tip = document.getElementById("tip");
  const SERIES = ["var(--s1)", "var(--s2)"];

  const FMT = {
    pct: v => `${v.toFixed(Math.abs(v) >= 10 ? 1 : 2)}%`,
    index: v => v.toLocaleString(undefined, {maximumFractionDigits: 0}),
    usd: v => "$" + v.toLocaleString(undefined, {maximumFractionDigits: 0}),
    usdm: v => `$${(v / 1e6).toFixed(1)}M`,
  };
  const day = s => new Date(s + "T00:00:00Z");
  const fmtDate = s => day(s).toLocaleDateString(undefined, {year: "numeric", month: "short", day: "numeric", timeZone: "UTC"});

  fetch("data/index.json").then(r => r.json()).then(idx => {
    const a = asOf(idx.generated_at);
    const box = document.getElementById("asof");
    box.textContent = a.long.split(" · ")[0];
    if (a.old) box.classList.add("old");
    const tiles = idx.apps.reduce((n, x) => n + x.tiles, 0), charts = idx.apps.reduce((n, x) => n + x.charts, 0);
    document.getElementById("counts").textContent = `${idx.apps.length} dashboards · ${tiles} tiles · ${charts} charts`;

    const cards = document.getElementById("cards");
    idx.apps.forEach((app, i) => {
      const href = `app.html?app=${encodeURIComponent(app.slug)}`;
      const p = app.preview;
      const el = document.createElement("article");
      el.className = "card";
      el.innerHTML = `
        <div class="card-head"><span class="card-num">${String(i + 1).padStart(2, "0")}</span>
          <h3><a href="${href}">${esc(app.name)}</a></h3></div>
        ${p ? `<figure class="fig">
          <div class="fig-legend">${p.series.length > 1 ? p.series.map((s, k) =>
            `<span><i style="background:${SERIES[k]}"></i>${esc(s.label)}</span>`).join("") : ""}</div>
          <div class="chart" role="img" aria-label="${esc(p.caption)}"></div>
          <figcaption>${esc(p.caption)}. <b>Latest ${p.series.map(s =>
            `${p.series.length > 1 ? esc(s.label.toLowerCase()) + " " : ""}${FMT[p.fmt](s.y[s.y.length - 1])}`).join(", ")}</b>
            (${fmtDate(p.series[0].x[p.series[0].x.length - 1])}).</figcaption>
        </figure>` : ""}
        <p class="card-blurb">${esc(app.blurb)}</p>
        <div class="card-foot"><span>${app.tiles} tiles · ${app.charts} charts</span><a href="${href}">Open dashboard →</a></div>`;
      cards.appendChild(el);
      if (p) {
        const chart = el.querySelector(".chart");
        chart._p = p;
        sizer.observe(chart);
      }
    });
  });

  // Draw once the card has its real width, and again whenever that width changes.
  const sizer = new ResizeObserver(entries => {
    for (const e of entries) {
      const w = Math.round(e.contentRect.width);
      if (w && w !== e.target._w) { e.target._w = w; draw(e.target); }
    }
  });

  function niceTicks(lo, hi, n = 4) {
    const span = hi - lo || Math.abs(hi) || 1;
    const raw = span / n, mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw);
    const ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) ticks.push(+v.toFixed(10));
    return ticks;
  }

  function draw(chart) {
    const p = chart._p;
    const W = chart.clientWidth, H = chart.clientHeight;
    if (!W) return;
    const padL = 44, padR = 8, padT = 6, padB = 20;
    const all = p.series.flatMap(s => s.y);
    let lo = Math.min(...all), hi = Math.max(...all);
    const ticks = niceTicks(lo, hi);
    lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
    const t0 = Math.min(...p.series.map(s => +day(s.x[0]))), t1 = Math.max(...p.series.map(s => +day(s.x[s.x.length - 1])));
    const X = t => padL + (t - t0) / (t1 - t0 || 1) * (W - padL - padR);
    const Y = v => padT + (1 - (v - lo) / (hi - lo || 1)) * (H - padT - padB);
    const tickFmt = v => p.fmt === "usdm" ? `$${(v / 1e6).toFixed(v % 1e6 ? 1 : 0)}M`
      : p.fmt === "pct" ? `${+v.toFixed(2)}%` : p.fmt === "usd" ? "$" + v.toLocaleString() : v.toLocaleString();

    let svg = "";
    for (const v of ticks) {
      svg += `<line class="gl" x1="${padL}" x2="${W - padR}" y1="${Y(v)}" y2="${Y(v)}"/>`;
      svg += `<text class="ax" x="${padL - 6}" y="${Y(v) + 3.5}" text-anchor="end">${tickFmt(v)}</text>`;
    }
    if (lo < 0 && hi > 0) svg += `<line class="zero" x1="${padL}" x2="${W - padR}" y1="${Y(0)}" y2="${Y(0)}"/>`;
    const y0 = new Date(t0).getUTCFullYear(), y1 = new Date(t1).getUTCFullYear();
    svg += `<text class="ax" x="${padL}" y="${H - 4}">${y0}</text>`;
    svg += `<text class="ax" x="${W - padR}" y="${H - 4}" text-anchor="end">${y1}</text>`;
    p.series.forEach((s, k) => {
      const d = s.x.map((x, j) => `${j ? "L" : "M"}${X(+day(x)).toFixed(1)},${Y(s.y[j]).toFixed(1)}`).join("");
      svg += `<path class="ln" d="${d}" style="stroke:${SERIES[k]}"/>`;
    });
    svg += `<g class="hover" visibility="hidden"><line class="xh" y1="${padT}" y2="${H - padB}"/>${p.series.map((_, k) =>
      `<circle class="dot" r="4" style="fill:${SERIES[k]}"/>`).join("")}</g>`;
    chart.innerHTML = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">${svg}</svg>`;

    const g = chart.querySelector(".hover"), xh = g.querySelector("line"), dots = g.querySelectorAll("circle");
    const nearest = (s, t) => {
      let a = 0, b = s.x.length - 1;
      while (b - a > 1) { const m = (a + b) >> 1; if (+day(s.x[m]) < t) a = m; else b = m; }
      return Math.abs(+day(s.x[a]) - t) <= Math.abs(+day(s.x[b]) - t) ? a : b;
    };
    const move = e => {
      const r = chart.getBoundingClientRect();
      const px = Math.max(padL, Math.min(W - padR, e.clientX - r.left));
      const t = t0 + (px - padL) / (W - padL - padR) * (t1 - t0);
      const hits = p.series.map(s => { const j = nearest(s, t); return {s, j, t: +day(s.x[j])}; });
      const tx = X(hits[0].t);
      xh.setAttribute("x1", tx); xh.setAttribute("x2", tx);
      hits.forEach((h, k) => { dots[k].setAttribute("cx", X(h.t)); dots[k].setAttribute("cy", Y(h.s.y[h.j])); });
      g.setAttribute("visibility", "visible");
      tip.innerHTML = `<div class="d">${fmtDate(hits[0].s.x[hits[0].j])}</div>` + hits.map((h, k) =>
        `<div class="r"><i style="background:${SERIES[k]}"></i>${esc(h.s.label)}<b>${FMT[p.fmt](h.s.y[h.j])}</b></div>`).join("");
      tip.hidden = false;
      const tw = tip.offsetWidth;
      const left = e.clientX + 14 + tw > window.innerWidth - 8 ? e.clientX - 14 - tw : e.clientX + 14;
      tip.style.left = `${left}px`;
      tip.style.top = `${r.top + 4}px`;
    };
    const leave = () => { g.setAttribute("visibility", "hidden"); tip.hidden = true; };
    chart.onpointermove = move;
    chart.onpointerdown = move;
    chart.onpointerleave = leave;
  }
})();
