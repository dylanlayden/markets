/* Homepage: byline, dashboard cards and their mini charts (plain SVG, no Plotly).
   Preview kinds come from build_site.py: line, curve, bars, flow (line may set log). */
(() => {
  // ?og: the build screenshots the homepage for the link-preview image (see build_site.py)
  const ogq = new URLSearchParams(location.search);
  if (ogq.has("og")) document.documentElement.classList.add("og");
  if (ogq.get("og")) document.documentElement.dataset.solo = ogq.get("og");  // ?og=N: card N alone
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const tip = document.getElementById("tip");
  const C = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];
  const SHORT = {"Mine production": "Mine", "Recycled (scrap)": "Recycled", "OTC & unreported": "OTC & other"};
  const short = s => SHORT[s] || s;

  const FMT = {
    pct: v => `${v.toFixed(2)}%`,
    tonnes: v => `${Math.round(v).toLocaleString()} t`,
  };
  const TICK = {
    pct: v => `${+v.toFixed(2)}%`,
    tonnes: v => v.toLocaleString(),
  };
  const day = s => new Date(s + "T00:00:00Z");
  const fmtDate = s => day(s).toLocaleDateString(undefined, {year: "numeric", month: "short", day: "numeric", timeZone: "UTC"});
  const last = a => a[a.length - 1];

  // One short line under each chart with the current reading.
  function latest(p) {
    if (p.kind === "curve") {
      const i = p.series[0].x.indexOf(10);
      return `10-year <b>${FMT.pct(p.series[0].y[i])}</b> today vs ${FMT.pct(p.series[1].y[i])} a year ago`;
    }
    if (p.kind === "flow") {
      const tot = p.demand.reduce((n, d) => n + d.value, 0);
      const top = [...p.demand].sort((a, b) => b.value - a.value)[0];
      return `<b>${FMT.tonnes(tot)}</b> supplied; largest use ${esc(top.label.toLowerCase())} at ${Math.round(top.value / tot * 100)}%`;
    }
    if (p.kind === "bars") {
      const mm = p.series.find(s => s.label === "Managed money") || p.series[0];
      return `${esc(mm.label)} net <b>${last(mm.y) > 0 ? "+" : ""}${FMT.tonnes(last(mm.y))}</b> (${fmtDate(last(p.x))})`;
    }
    return p.series.map(s => `${p.series.length > 1 ? esc(s.label) + " " : ""}<b>${FMT[p.fmt](last(s.y))}</b>`).join(" · ")
      + ` (${fmtDate(last(p.series[0].x))})`;
  }

  // Counter pills under the intro (after Our World in Data's homepage counts).
  const svg = d => `<svg viewBox="0 0 16 16" aria-hidden="true">${d}</svg>`;
  const ICON = {
    grid: svg('<rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/>'),
    chart: svg('<path d="M2 13.5h12"/><path d="M3 11l3.2-3.6 2.6 2.2L13 4.5"/>'),
    tiles: svg('<rect x="2" y="2.5" width="12" height="11" rx="1.5"/><path d="M2 6.5h12M7 6.5v7"/>'),
    db: svg('<ellipse cx="8" cy="3.8" rx="5.5" ry="1.8"/><path d="M2.5 3.8v8.4c0 1 2.5 1.8 5.5 1.8s5.5-.8 5.5-1.8V3.8"/><path d="M2.5 8c0 1 2.5 1.8 5.5 1.8s5.5-.8 5.5-1.8"/>'),
  };
  function renderStats(items) {
    const box = document.getElementById("stats");
    box.innerHTML = items.map(s => {
      const tag = s.href ? "a" : "span";
      return `<${tag} class="stat"${s.href ? ` href="${s.href}"` : ""}${s.title ? ` title="${esc(s.title)}"` : ""}>
        ${s.icon}<b data-n="${s.n}">${s.n}</b> ${esc(s.label)}</${tag}>`;
    }).join("");
    if (matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.classList.contains("og")) return;
    const nums = [...box.querySelectorAll("b[data-n]")], t0 = performance.now(), dur = 900;
    nums.forEach(b => { b.style.minWidth = `${b.offsetWidth}px`; b.textContent = "0"; });
    const tick = now => {
      const k = Math.min(1, (now - t0) / dur), e = 1 - (1 - k) ** 3;
      nums.forEach(b => { b.textContent = Math.round(+b.dataset.n * e).toLocaleString(); });
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  function legend(p) {
    const items = p.kind === "flow" ? p.supply.map(s => short(s.label))
      : p.series.length > 1 ? p.series.map(s => s.label) : [];
    return items.map((l, k) => `<span><i style="background:${C[k]}"></i>${esc(l)}</span>`).join("");
  }

  fetch("data/index.json", {cache: "no-cache"}).then(r => r.json()).then(idx => {
    const a = asOf(idx.generated_at);
    const box = document.getElementById("asof");
    box.textContent = a.long.split(" · ")[0];
    if (a.old) box.classList.add("old");
    const tiles = idx.apps.reduce((n, x) => n + x.tiles, 0), charts = idx.apps.reduce((n, x) => n + x.charts, 0);
    renderStats([
      {n: idx.apps.length, label: "dashboards", href: "#dashboards", icon: ICON.grid},
      {n: charts, label: "charts", icon: ICON.chart},
      {n: tiles, label: "tiles", icon: ICON.tiles},
      {n: (idx.sources || []).length, label: "data sources", href: "#about", icon: ICON.db,
       title: (idx.sources || []).join(", ")},
    ].filter(s => s.n));

    const cards = document.getElementById("cards");
    idx.apps.forEach((app, i) => {
      const href = `app.html?app=${encodeURIComponent(app.slug)}`;
      const p = app.preview;
      const el = document.createElement("article");
      el.className = "card";
      el.innerHTML = `
        <div class="card-num">${String(i + 1).padStart(2, "0")}</div>
        <h3><a href="${href}" title="${esc(app.blurb)}">${esc(app.name)}</a></h3>
        ${p ? `<figure class="fig">
          <figcaption class="fig-title">${esc(p.caption)}</figcaption>
          <div class="fig-legend">${legend(p)}</div>
          <div class="chart" role="img" aria-label="${esc(p.caption)}"></div>
          <p class="fig-latest">${latest(p)}</p>
        </figure>` : `<p class="card-blurb">${esc(app.blurb)}</p>`}
        <div class="card-foot"><span>${app.charts} charts</span><a href="${href}">Open →</a></div>`;
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

  function showTip(e, chart, html) {
    tip.innerHTML = html;
    tip.hidden = false;
    const r = chart.getBoundingClientRect(), tw = tip.offsetWidth;
    tip.style.left = `${e.clientX + 14 + tw > window.innerWidth - 8 ? e.clientX - 14 - tw : e.clientX + 14}px`;
    tip.style.top = `${r.top + 4}px`;
  }
  const row = (k, label, val) => `<div class="r"><i style="background:${C[k]}"></i>${esc(label)}<b>${val}</b></div>`;

  function draw(chart) {
    const p = chart._p, W = chart.clientWidth, H = chart.clientHeight;
    if (!W) return;
    (p.kind === "flow" ? drawFlow : drawXY)(chart, p, W, H);
  }

  /* line / curve / bars share axes and a crosshair */
  function drawXY(chart, p, W, H) {
    const padL = p.fmt === "tonnes" ? 40 : 38, padR = 6, padT = 6, padB = 18;
    const bars = p.kind === "bars", curve = p.kind === "curve";
    let lo, hi;
    if (bars) {
      const pos = p.x.map((_, j) => p.series.reduce((n, s) => n + Math.max(0, s.y[j]), 0));
      const neg = p.x.map((_, j) => p.series.reduce((n, s) => n + Math.min(0, s.y[j]), 0));
      lo = Math.min(...neg); hi = Math.max(...pos);
    } else {
      const all = p.series.flatMap(s => s.y);
      lo = Math.min(...all); hi = Math.max(...all);
    }
    let ticks;
    if (p.log) {  // fixed 1-2-5 steps; the scale works in log10 units
      ticks = [0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50].filter(v => v >= lo * 0.98 && v <= hi * 1.02);
      lo = Math.log10(lo * 0.9); hi = Math.log10(hi * 1.1);
    } else {
      ticks = niceTicks(lo, hi, 3);
      lo = Math.min(lo, ticks[0]); hi = Math.max(hi, last(ticks));
    }

    // x scale: dates (line, bars) or log maturity (curve)
    const xs = curve ? p.series[0].x : bars ? p.x.map(d => +day(d)) : null;
    const xv = curve ? (p.ticks.log ? Math.log : v => v) : v => v;
    const t0 = curve ? xv(xs[0]) : bars ? xs[0] : Math.min(...p.series.map(s => +day(s.x[0])));
    const t1 = curve ? xv(last(xs)) : bars ? last(xs) : Math.max(...p.series.map(s => +day(last(s.x))));
    const plotW = W - padL - padR;
    const X = t => padL + (t - t0) / (t1 - t0 || 1) * plotW;
    const Y = v => padT + (1 - ((p.log ? Math.log10(v) : v) - lo) / (hi - lo || 1)) * (H - padT - padB);

    let svg = "";
    for (const v of ticks) {
      svg += `<line class="gl" x1="${padL}" x2="${W - padR}" y1="${Y(v)}" y2="${Y(v)}"/>`;
      svg += `<text class="ax" x="${padL - 5}" y="${Y(v) + 3.5}" text-anchor="end">${TICK[p.fmt](v)}</text>`;
    }
    if (!p.log && lo < 0 && hi > 0) svg += `<line class="zero" x1="${padL}" x2="${W - padR}" y1="${Y(0)}" y2="${Y(0)}"/>`;

    if (curve) {
      const show = ["3M", "2Y", "10Y", "30Y"];
      p.ticks.vals.forEach((v, j) => {
        if (!show.includes(p.ticks.text[j])) return;
        const anchor = j === 0 ? "start" : j === p.ticks.vals.length - 1 ? "end" : "middle";
        svg += `<text class="ax" x="${X(xv(v))}" y="${H - 3}" text-anchor="${anchor}">${p.ticks.text[j]}</text>`;
      });
    } else {
      svg += `<text class="ax" x="${padL}" y="${H - 3}">${new Date(t0).getUTCFullYear()}</text>`;
      svg += `<text class="ax" x="${W - padR}" y="${H - 3}" text-anchor="end">${new Date(t1).getUTCFullYear()}</text>`;
    }

    if (bars) {
      const bw = plotW / p.x.length;
      p.x.forEach((_, j) => {
        let up = 0, dn = 0;
        const x = padL + j * bw;
        p.series.forEach((s, k) => {
          const v = s.y[j];
          if (!v) return;
          const a = v > 0 ? up : dn, b = a + v;
          if (v > 0) up = b; else dn = b;
          svg += `<rect x="${x.toFixed(2)}" width="${Math.max(0.8, bw - 0.6).toFixed(2)}" y="${Y(Math.max(a, b)).toFixed(2)}" height="${Math.abs(Y(a) - Y(b)).toFixed(2)}" style="fill:${C[k]}"/>`;
        });
      });
    } else {
      p.series.forEach((s, k) => {
        const d = s.x.map((x, j) => `${j ? "L" : "M"}${X(curve ? xv(x) : +day(x)).toFixed(1)},${Y(s.y[j]).toFixed(1)}`).join("");
        svg += `<path class="ln${k ? " ln2" : ""}" d="${d}" style="stroke:${C[k]}"/>`;
      });
    }
    svg += `<g class="hover" visibility="hidden"><line class="xh" y1="${padT}" y2="${H - padB}"/>${bars ? "" : p.series.map((_, k) =>
      `<circle class="dot" r="3.5" style="fill:${C[k]}"/>`).join("")}</g>`;
    chart.innerHTML = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">${svg}</svg>`;

    const g = chart.querySelector(".hover"), xh = g.querySelector("line"), dots = g.querySelectorAll("circle");
    const nearestIn = (arr, t) => {
      let a = 0, b = arr.length - 1;
      while (b - a > 1) { const m = (a + b) >> 1; if (arr[m] < t) a = m; else b = m; }
      return Math.abs(arr[a] - t) <= Math.abs(arr[b] - t) ? a : b;
    };
    const move = e => {
      const r = chart.getBoundingClientRect();
      const px = Math.max(padL, Math.min(W - padR, e.clientX - r.left));
      let html, cx;
      if (bars) {
        const j = Math.min(p.x.length - 1, Math.floor((px - padL) / (plotW / p.x.length)));
        cx = padL + (j + 0.5) * (plotW / p.x.length);
        html = `<div class="d">${fmtDate(p.x[j])}</div>` + p.series.map((s, k) => row(k, s.label, FMT.tonnes(s.y[j]))).join("");
      } else {
        const t = t0 + (px - padL) / plotW * (t1 - t0);
        const hits = p.series.map(s => {
          const arr = curve ? s.x.map(xv) : s.x.map(d => +day(d));
          const j = nearestIn(arr, t);
          return {s, j, t: arr[j]};
        });
        cx = X(hits[0].t);
        hits.forEach((h, k) => { dots[k].setAttribute("cx", X(h.t)); dots[k].setAttribute("cy", Y(h.s.y[h.j])); });
        const head = curve ? `${p.ticks.text[p.ticks.vals.indexOf(hits[0].s.x[hits[0].j])] ?? hits[0].s.x[hits[0].j] + "Y"} Treasury`
          : fmtDate(hits[0].s.x[hits[0].j]);
        html = `<div class="d">${head}</div>` + hits.map((h, k) => row(k, h.s.label, FMT[p.fmt](h.s.y[h.j]))).join("");
      }
      xh.setAttribute("x1", cx); xh.setAttribute("x2", cx);
      g.setAttribute("visibility", "visible");
      showTip(e, chart, html);
    };
    chart.onpointermove = chart.onpointerdown = move;
    chart.onpointerleave = () => { g.setAttribute("visibility", "hidden"); tip.hidden = true; };
  }

  /* two-stage Sankey: stacked supply bar on the left, flows to labelled demand nodes */
  function drawFlow(chart, p, W, H) {
    const tot = p.demand.reduce((n, d) => n + d.value, 0);
    const supTot = p.supply.reduce((n, d) => n + d.value, 0);
    const labelW = Math.min(104, W * 0.46), barW = 8, nodeW = 5, padT = 2, padB = 2;
    const gap = 3, rightX = W - labelW - nodeW;
    const usable = H - padT - padB - gap * (p.demand.length - 1);
    const k = usable / tot;

    let svg = "", y = padT;
    p.supply.forEach((s, i) => {
      const h = s.value / supTot * (H - padT - padB);
      svg += `<rect x="0" y="${y.toFixed(2)}" width="${barW}" height="${Math.max(0, h - 1).toFixed(2)}" style="fill:${C[i]}" data-s="${i}"/>`;
      y += h;
    });

    // flows leave the supply bar in order and land on each demand node
    const scaleL = (H - padT - padB) / tot;
    let yl = padT, yr = padT;
    const nodes = p.demand.map(d => {
      const hL = d.value * scaleL, hR = d.value * k;
      const n = {d, l0: yl, l1: yl + hL, r0: yr, r1: yr + hR};
      yl += hL; yr += hR + gap;
      return n;
    });
    const mx = (barW + rightX) / 2;
    nodes.forEach((n, i) => {
      svg += `<path class="flow" data-d="${i}" d="M${barW},${n.l0.toFixed(2)} C${mx},${n.l0.toFixed(2)} ${mx},${n.r0.toFixed(2)} ${rightX},${n.r0.toFixed(2)}
        L${rightX},${n.r1.toFixed(2)} C${mx},${n.r1.toFixed(2)} ${mx},${n.l1.toFixed(2)} ${barW},${n.l1.toFixed(2)} Z"/>`;
      svg += `<rect class="node" x="${rightX}" y="${n.r0.toFixed(2)}" width="${nodeW}" height="${Math.max(1, n.r1 - n.r0).toFixed(2)}" data-d="${i}"/>`;
    });

    // labels at node centres, pushed apart so they never overlap
    const minGap = 12.5;
    const ys = nodes.map(n => (n.r0 + n.r1) / 2);
    for (let i = 1; i < ys.length; i++) ys[i] = Math.max(ys[i], ys[i - 1] + minGap);
    const over = last(ys) - (H - 4);
    if (over > 0) for (let i = ys.length - 1; i >= 0; i--) ys[i] = Math.min(ys[i] - over, i < ys.length - 1 ? ys[i + 1] - minGap : Infinity);
    nodes.forEach((n, i) => {
      svg += `<text class="fl" x="${rightX + nodeW + 5}" y="${(ys[i] + 3.5).toFixed(2)}">${esc(short(n.d.label))} <tspan class="fl-v">${Math.round(n.d.value / tot * 100)}%</tspan></text>`;
    });
    chart.innerHTML = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">${svg}</svg>`;
    chart.classList.add("is-flow");

    chart.onpointermove = chart.onpointerdown = e => {
      const t = e.target;
      chart.querySelectorAll(".flow.on").forEach(f => f.classList.remove("on"));
      if (t.dataset.d !== undefined) {
        const d = p.demand[+t.dataset.d];
        chart.querySelector(`.flow[data-d="${t.dataset.d}"]`).classList.add("on");
        showTip(e, chart, `<div class="d">Demand</div><div class="r">${esc(d.label)}<b>${FMT.tonnes(d.value)} · ${Math.round(d.value / tot * 100)}%</b></div>`);
      } else if (t.dataset.s !== undefined) {
        const s = p.supply[+t.dataset.s];
        showTip(e, chart, `<div class="d">Supply</div>${row(+t.dataset.s, s.label, `${FMT.tonnes(s.value)} · ${Math.round(s.value / supTot * 100)}%`)}`);
      } else tip.hidden = true;
    };
    chart.onpointerleave = () => { chart.querySelectorAll(".flow.on").forEach(f => f.classList.remove("on")); tip.hidden = true; };
  }
})();
