/* Renders one snapshot app: grid layout, lazy tile loading, param variants. */
(() => {
  const slug = new URLSearchParams(location.search).get("app");
  const grid = document.getElementById("grid");
  const cache = new Map();
  const groupValues = {};
  const tileValues = new Map();   // tile id -> {param: value}
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const parseKey = k => Object.fromEntries((k ? k.split("&") : []).map(kv => kv.split("=")));
  const makeKey = o => Object.keys(o).sort().map(k => `${k}=${o[k]}`).join("&");

  const getJSON = url => {
    if (!cache.has(url)) cache.set(url, fetch(url).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }));
    return cache.get(url);
  };

  fetch("data/index.json").then(r => r.json()).then(idx => {
    document.getElementById("nav").innerHTML = idx.apps.map(a =>
      `<a href="app.html?app=${a.slug}" class="${a.slug === slug ? "on" : ""}">${esc(a.name)}</a>`).join("");
  });

  if (!slug) { location.replace("./"); return; }

  getJSON(`data/${slug}/manifest.json`).then(m => {
    document.title = `${m.name} · Markets Research Terminal`;
    document.getElementById("title").textContent = m.name;
    document.getElementById("blurb").textContent = m.blurb;
    document.getElementById("sources").textContent = "Sources: " + m.sources;
    const a = asOf(m.generated_at), box = document.getElementById("asof");
    document.getElementById("stamp").textContent = a.short;
    box.className = "asof" + (a.old ? " old" : "");
    box.textContent = a.long;

    const groupBox = document.getElementById("groups");
    for (const g of m.groups) {
      groupValues[g.name] = g.default;
      const lab = document.createElement("label");
      lab.className = "ctl";
      lab.innerHTML = `${esc(g.label)} <select>${g.options.map(o =>
        `<option value="${esc(o.value)}"${o.value === g.default ? " selected" : ""}>${esc(o.label)}</option>`).join("")}</select>`;
      lab.querySelector("select").addEventListener("change", e => {
        groupValues[g.name] = e.target.value;
        m.tiles.filter(t => t.group === g.name).forEach(t => render(t, true));
      });
      groupBox.appendChild(lab);
    }

    const io = new IntersectionObserver(entries => {
      for (const e of entries) if (e.isIntersecting) { io.unobserve(e.target); render(e.target._tile); }
    }, {rootMargin: "800px 0px"});

    for (const t of m.tiles) {
      tileValues.set(t.id, parseKey(t.default));
      const isHdr = t.type === "markdown" && (t.h <= 3 || /hdr/.test(t.id));
      const el = document.createElement("section");
      el.className = `tile ${t.type}${isHdr ? " hdr" : ""}`;
      el.style.gridColumn = `${t.x + 1} / span ${t.w}`;
      el.style.gridRow = `${t.y + 1} / span ${t.h}`;
      const own = t.params.filter(p => p.name !== t.group);
      el.innerHTML = `
        <header>
          <span class="t">${esc(t.name)}</span>
          ${t.stale ? '<span class="stale" title="Latest refresh failed; showing the previous snapshot">stale</span>' : ""}
          ${own.map(p => `<select data-p="${esc(p.name)}" aria-label="${esc(p.label)}">${p.options.map(o =>
            `<option value="${esc(o.value)}"${o.value === tileValues.get(t.id)[p.name] ? " selected" : ""}>${esc(o.label)}</option>`).join("")}</select>`).join("")}
          ${t.description ? `<span class="i" title="${esc(t.description)}">ⓘ</span>` : ""}
        </header>
        <div class="body${t.type === "chart" ? "" : t.type === "table" ? " table" : " scroll"}"></div>`;
      el.querySelectorAll("select[data-p]").forEach(s => s.addEventListener("change", () => {
        tileValues.get(t.id)[s.dataset.p] = s.value;
        render(t, true);
      }));
      el._tile = t;
      t._el = el;
      grid.appendChild(el);
      io.observe(el);
    }
  }).catch(() => {
    document.getElementById("title").textContent = "Dashboard not found";
  });

  function render(t, force) {
    if (t._rendered && !force) return;
    t._rendered = true;
    const vals = {...tileValues.get(t.id)};
    if (t.group && groupValues[t.group] !== undefined) vals[t.group] = groupValues[t.group];
    const file = t.variants[makeKey(vals)];
    const body = t._el.querySelector(".body");
    if (!file) { body.innerHTML = '<div class="msg">Not available in this snapshot.</div>'; return; }
    getJSON(`data/${slug}/${file}`).then(payload => {
      if (t.type === "chart") return drawChart(body, payload);
      if (t.type === "markdown") return drawMarkdown(body, payload);
      return drawTable(body, payload);
    }).catch(() => { body.innerHTML = '<div class="msg">Could not load this tile.</div>'; });
  }

  function drawChart(body, fig) {
    let plot = body.querySelector(".plot");
    if (!plot) { plot = document.createElement("div"); plot.className = "plot"; body.appendChild(plot); }
    const layout = {...fig.layout, autosize: true};
    delete layout.width; delete layout.height;
    Plotly.react(plot, fig.data, layout, {
      responsive: true, displaylogo: false,
      modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines"],
    });
  }

  function drawMarkdown(body, md) {
    body.innerHTML = `<div class="md">${DOMPurify.sanitize(marked.parse(md))}</div>`;
    body.querySelectorAll("a").forEach(a => { a.target = "_blank"; a.rel = "noopener"; });
  }

  function drawTable(body, rows) {
    if (!rows.length) { body.innerHTML = '<div class="msg">No rows.</div>'; return; }
    const cols = [...new Set(rows.flatMap(r => Object.keys(r)))];
    const numeric = cols.map(c => rows.every(r => r[c] == null || typeof r[c] === "number"));
    const fmt = (v, num) => {
      if (v == null) return "";
      if (!num) return esc(v);
      const a = Math.abs(v);
      return v.toLocaleString(undefined, {maximumFractionDigits: a >= 1000 ? 0 : a >= 1 ? 2 : 4});
    };
    const label = c => c.replace(/_/g, " ");
    let sortCol = -1, asc = false;
    const paint = () => {
      const data = sortCol < 0 ? rows : [...rows].sort((a, b) => {
        const x = a[cols[sortCol]], y = b[cols[sortCol]];
        if (x == null) return 1; if (y == null) return -1;
        const d = numeric[sortCol] ? x - y : String(x).localeCompare(String(y));
        return asc ? d : -d;
      });
      body.innerHTML = `<table class="data"><thead><tr>${cols.map((c, i) =>
        `<th data-i="${i}" class="${i === sortCol ? "sorted" + (asc ? " asc" : "") : ""}">${esc(label(c))}</th>`).join("")}</tr></thead>
        <tbody>${data.map(r => `<tr>${cols.map((c, i) =>
          `<td class="${numeric[i] ? "num" : ""}">${fmt(r[c], numeric[i])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
      body.querySelectorAll("th").forEach(th => th.addEventListener("click", () => {
        const i = +th.dataset.i;
        asc = sortCol === i ? !asc : false;
        sortCol = i;
        paint();
      }));
    };
    paint();
  }
})();
