#!/usr/bin/env python3
"""Snapshot the local OpenBB custom backend into a static, read-only website.

Reads /widgets.json and /apps.json from the backend (default http://127.0.0.1:6901),
fetches every tile of the showcase apps, and writes a self-contained site to ./site:

  site/index.html, site/app.html, site/assets/*      copied from ./web
  site/data/index.json                               app list + build time
  site/data/<app>/manifest.json                      grid layout + widget metadata
  site/data/<app>/<widget>__<variant>.json           chart / table / markdown payloads

Widgets with dropdown params are pre-rendered for every option combination (up to
MAX_VARIANTS); free-text params render their default only.

Nothing here talks to anything but the local backend. The output is scanned for the
FRED key and generic credential patterns before the script reports success.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import hashlib
import itertools
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:6901")
ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
SITE = ROOT / "site"
DATA = SITE / "data"

MAX_VARIANTS = 40      # per widget; beyond this only the default is rendered
WORKERS = 4            # the backend handles 30 concurrent; stay polite to upstreams
RETRIES = 3
TIMEOUT = 240

# Showcase apps, in display order. Gold Price Formation is off the homepage for now
# (kept on the backend). Silver Market is held back: its core tiles are derived from
# the World Silver Survey (licensed publication).
SHOWCASE = [
    {
        "name": "Macro Factors",
        "slug": "macro",
        "blurb": "US rates, credit, inflation, growth, labor and global yields — 20 charts with recession shading.",
        "sources": "FRED (Federal Reserve Bank of St. Louis) via OpenBB Platform; NBER recession dates.",
        "preview": {"tile": "macro_yield_curve", "kind": "curve", "fmt": "pct",
                    "series": [["Today", "Today"], ["1Y ago", "1 year ago"]],
                    "caption": "US Treasury yield curve"},
    },
    {
        "name": "Housing & SF Real Estate",
        "slug": "housing",
        "blurb": "US housing macro down to San Francisco ZIP codes: prices, momentum, rents and gross yields.",
        "sources": "FRED (S&P CoreLogic Case-Shiller, Realtor.com, Freddie Mac, BLS); Zillow Research (ZHVI, ZORI); Redfin Data Center.",
        "preview": {"tile": "re_us_mortgage", "kind": "line", "fmt": "pct",
                    "series": [["30Y fixed", "30-year"], ["15Y fixed", "15-year"]],
                    "caption": "US fixed mortgage rates"},
    },
    {
        "name": "Gold Market",
        "slug": "gold",
        "blurb": "Gold supply and demand, central-bank buying, ETF flows, futures positioning and producers.",
        "sources": "World Gold Council (Goldhub); LBMA; CFTC; Yahoo Finance.",
        "preview": {"tile": "gd_sankey", "kind": "flow", "fmt": "tonnes",
                    "caption": "Gold supply to demand, trailing four quarters"},
    },
    {
        "name": "HYPE · Hyperliquid Cash Flow",
        "slug": "hype",
        "blurb": "Hyperliquid valued as a cash-flowing asset: fees, revenue, buybacks, multiples and market structure.",
        "sources": "DefiLlama; Hyperliquid public info API; CoinGecko; OKX; FRED.",
        "preview": {"tile": "hy_buyback_yield", "kind": "line", "fmt": "pct",
                    "series": [["Buyback yield (30d-annualised rev ÷ mkt cap)", "Buyback yield"]],
                    "caption": "HYPE buyback yield, annualized"},
    },
]


PREVIEW_POINTS = 180   # homepage mini charts are downsampled to about this many points


def decode(v):
    """Plotly 6 ships arrays as {"dtype", "bdata"} (base64); expand to a plain list."""
    if isinstance(v, dict) and "bdata" in v:
        import base64, numpy as np
        return np.frombuffer(base64.b64decode(v["bdata"]), dtype=np.dtype(v["dtype"])).tolist()
    return v


def _thin(pts: list, n: int = PREVIEW_POINTS) -> list:
    """Every k-th point so about n remain, always keeping the latest."""
    step = max(1, -(-len(pts) // n))
    keep = pts[::step]
    return keep if keep[-1] == pts[-1] else keep + [pts[-1]]


def build_preview(cfg: dict, tiles: list[dict], outdir: Path) -> dict | None:
    """Small chart for the homepage card, taken from one of the app's own charts.

    kind  line  — time series, one or two lines
          curve — numeric x with tick labels (yield curve), one or two lines
          bars  — stacked +/- bars over time; a series may sum several traces
          flow  — two-stage Sankey (supply parts → total → demand parts)
    """
    pc = cfg.get("preview")
    if not pc:
        return None
    try:
        tile = next(t for t in tiles if t["id"] == pc["tile"])
        fig = json.loads((outdir / tile["variants"][tile["default"]]).read_text())
        out = {"kind": pc["kind"], "caption": pc["caption"], "fmt": pc["fmt"], "tile": tile["name"]}

        if pc["kind"] == "flow":
            d = fig["data"][0]
            labels = [re.sub(r"\s*\(residual\)", "", l.split("<br>")[0]) for l in d["node"]["label"]]
            src, tgt, val = (decode(d["link"][k]) for k in ("source", "target", "value"))
            hub = max(set(tgt), key=tgt.count)  # the node every supply link flows into
            out["supply"] = [{"label": labels[a], "value": round(v, 1)} for a, b, v in zip(src, tgt, val) if b == hub]
            out["demand"] = [{"label": labels[b], "value": round(v, 1)} for a, b, v in zip(src, tgt, val) if a == hub]
            return out

        traces = {d.get("name"): d for d in fig["data"]}
        if pc["kind"] == "curve":
            ax = fig["layout"].get("xaxis", {})
            out["ticks"] = {"vals": ax.get("tickvals"), "text": ax.get("ticktext"), "log": ax.get("type") == "log"}
            out["series"] = [{"label": label, "x": decode(traces[name]["x"]),
                              "y": [round(v, 4) for v in decode(traces[name]["y"])]} for name, label in pc["series"]]
            return out

        if pc["kind"] == "bars":
            x = [str(v)[:10] for v in decode(traces[pc["series"][0][0]]["x"])]
            cols = []
            for names, label in pc["series"]:
                names = names if isinstance(names, list) else [names]
                ys = [decode(traces[n]["y"]) for n in names]
                cols.append((label, [sum(v for v in vals if v == v) for vals in zip(*ys)]))
            idx = _thin(list(range(len(x))), 90)
            out["x"] = [x[i] for i in idx]
            out["series"] = [{"label": label, "y": [round(ys[i], 1) for i in idx]} for label, ys in cols]
            return out

        series = []
        for name, label in pc["series"]:
            d = traces[name]
            pts = [(str(x)[:10], y) for x, y in zip(decode(d["x"]), decode(d["y"]))
                   if isinstance(y, (int, float)) and y == y]
            keep = _thin(pts)
            series.append({"label": label, "x": [p[0] for p in keep], "y": [round(p[1], 4) for p in keep]})
        out["series"] = series
        return out
    except Exception as e:  # noqa: BLE001 — a missing preview should never fail the build
        log(f"  preview skipped for {cfg['slug']}: {e}")
        return None


def log(*a):
    print(*a, flush=True)


def get_json(path: str, params: dict | None = None):
    url = BACKEND.rstrip("/") + "/" + path.lstrip("/")
    if params:
        url += "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001 — upstream sources fail transiently
            last = e
            time.sleep(3 * (attempt + 1) ** 2)
    raise RuntimeError(f"{path} {params}: {last}")


# The backend's safe_chart/safe_md/safe_table guards answer 200 with an error card when a
# source fails. Treat those as failures so the last good snapshot is kept instead.
DEGRADED = re.compile(r"Feed unavailable(\.| for this tile)|source did not respond")


def degraded(payload) -> bool:
    return bool(DEGRADED.search(json.dumps(payload)))


def shape_ok(wtype: str, payload) -> bool:
    if wtype == "chart":
        return isinstance(payload, dict) and "data" in payload and "layout" in payload
    if wtype == "markdown":
        return isinstance(payload, str)
    return isinstance(payload, list)


def variants_for(widget: dict, tile: dict) -> list[dict]:
    """Every option combination for dropdown params, else just the default."""
    params = widget.get("params") or []
    if not params:
        return [{}]
    saved = (tile.get("state") or {}).get("params") or {}
    default = {p["paramName"]: str(saved.get(p["paramName"], p.get("value"))) for p in params}
    choices = []
    for p in params:
        opts = [str(o["value"]) for o in (p.get("options") or [])]
        if not opts:
            return [default]
        choices.append([(p["paramName"], v) for v in opts])
    combos = [dict(c) for c in itertools.product(*choices)]
    if len(combos) > MAX_VARIANTS:
        return [default]
    combos.sort(key=lambda c: c != default)  # default first
    return combos


def vkey(params: dict) -> str:
    return "&".join(f"{k}={params[k]}" for k in sorted(params))


def vfile(wid: str, params: dict) -> str:
    if not params:
        return f"{wid}.json"
    h = hashlib.sha1(vkey(params).encode()).hexdigest()[:10]
    return f"{wid}__{h}.json"


def build_app(cfg: dict, widgets: dict, apps: dict, ex: cf.Executor) -> dict:
    app = apps[cfg["name"]]
    outdir = DATA / cfg["slug"]
    outdir.mkdir(parents=True, exist_ok=True)
    groups = {g["name"]: g for g in app.get("groups") or []}

    tiles, jobs = [], []
    for tab in app["tabs"].values():
        for t in tab["layout"]:
            w = widgets[t["i"]]
            wtype = w.get("type") or "table"
            vs = variants_for(w, t)
            tile = {
                "id": t["i"], "x": t["x"], "y": t["y"], "w": t["w"], "h": t["h"],
                "type": wtype, "name": w.get("name", t["i"]),
                "description": w.get("description", ""),
                "params": [
                    {"name": p["paramName"], "label": p.get("label", p["paramName"]),
                     "options": [{"label": o.get("label", o["value"]), "value": str(o["value"])}
                                 for o in (p.get("options") or [])]}
                    for p in (w.get("params") or [])
                ] if len(vs) > 1 else [],
                "group": next((groups[g].get("paramName") for g in t.get("groups") or [] if g in groups), None),
                "default": vkey(vs[0]),
                "variants": {},
            }
            tiles.append(tile)
            for v in vs:
                # charts are fetched in both themes; the page picks one from the visitor's
                # light/dark setting. Dark is the canonical file, light sits beside it.
                for theme in (("dark", "light") if wtype == "chart" else (None,)):
                    q = dict(v, theme=theme) if theme else dict(v)
                    jobs.append((tile, v, theme, ex.submit(get_json, w["endpoint"], q)))

    ok = stale = failed = 0
    for tile in tiles:
        if tile["type"] == "chart":
            tile["light"] = True  # cleared below if any light variant is missing
    for tile, v, theme, fut in jobs:
        fname = vfile(tile["id"], v)
        if theme == "light":
            path = outdir / fname.replace(".json", ".light.json")
            try:
                payload = fut.result()
                if not shape_ok("chart", payload) or degraded(payload):
                    raise RuntimeError("bad light payload")
                path.write_text(json.dumps(payload, separators=(",", ":")))
            except Exception as e:  # noqa: BLE001 — the page falls back to the dark chart
                if not path.exists():
                    tile["light"] = False
                    log(f"  LIGHT {cfg['slug']}/{tile['id']} {vkey(v)}: {e}")
            continue
        path = outdir / fname
        try:
            payload = fut.result()
            if not shape_ok(tile["type"], payload):
                raise RuntimeError(f"unexpected {tile['type']} shape: {type(payload).__name__}")
            if degraded(payload):
                raise RuntimeError("backend served a 'feed unavailable' card")
            path.write_text(json.dumps(payload, separators=(",", ":")))
            tile["variants"][vkey(v)] = fname
            ok += 1
        except Exception as e:  # noqa: BLE001
            if path.exists():  # keep the last good snapshot rather than blanking the tile
                tile["variants"][vkey(v)] = fname
                tile["stale"] = True
                stale += 1
                log(f"  STALE {cfg['slug']}/{tile['id']} {vkey(v)}: {e}")
            else:
                failed += 1
                log(f"  FAIL  {cfg['slug']}/{tile['id']} {vkey(v)}: {e}")

    group_controls = []
    for g in groups.values():
        member = next((t for t in tiles if t["group"] == g.get("paramName") and t["params"]), None)
        if member:
            p = next(p for p in member["params"] if p["name"] == g["paramName"])
            group_controls.append({"name": g["paramName"], "label": g["name"],
                                   "default": str(g.get("defaultValue")), "options": p["options"]})

    tiles.sort(key=lambda t: (t["y"], t["x"]))
    manifest = {
        "slug": cfg["slug"], "name": cfg["name"], "blurb": cfg["blurb"], "sources": cfg["sources"],
        "description": app.get("description", ""), "generated_at": NOW,
        "groups": group_controls, "tiles": tiles,
    }
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    log(f"{cfg['name']}: {len(tiles)} tiles, {ok} payloads ok, {stale} stale, {failed} failed")
    return {"slug": cfg["slug"], "name": cfg["name"], "blurb": cfg["blurb"], "sources": cfg["sources"],
            "tiles": len(tiles), "charts": sum(t["type"] == "chart" for t in tiles),
            "preview": build_preview(cfg, tiles, outdir), "ok": ok, "stale": stale, "failed": failed}


SITE_URL = "https://dylanlayden.github.io/markets/"


def source_names(apps: list[dict]) -> list[str]:
    """Distinct data providers across the showcase, for the homepage counter."""
    seen = {}
    for a in apps:
        for part in a["sources"].rstrip(".").split(";"):
            name = re.split(r"\s*\(|\s+via\s", part.strip())[0].strip()
            if name:
                seen.setdefault(name.lower(), name)
    return sorted(seen.values(), key=str.lower)


def build_og(summary: list[dict]) -> None:
    """1200x630 link-preview image (LinkedIn, Slack, iMessage) drawn from today's previews."""
    try:
        import math
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.font_manager import FontProperties
    except Exception as e:  # noqa: BLE001
        log(f"  og image skipped: {e}")
        return
    sup = "/System/Library/Fonts/Supplemental/"
    serif = FontProperties(fname=sup + "Georgia Bold.ttf")
    sans = FontProperties(fname="/System/Library/Fonts/Helvetica.ttc")
    BG, INK, INK2, MUTED, RULE, GRID = "#f8f7f3", "#16191d", "#4a505a", "#6b7280", "#d9d5ca", "#ece9e1"
    S1, S2 = "#2b5c9e", "#c0702a"

    fig = plt.figure(figsize=(12, 6.3), dpi=100, facecolor=BG)
    fig.text(0.05, 0.875, "SELECTED RESEARCH DASHBOARDS", fontproperties=sans, fontsize=13, color=MUTED)
    fig.text(0.05, 0.75, "Markets Research Terminal", fontproperties=serif, fontsize=46, color=INK)
    names = " · ".join(a["name"].split(" · ")[0] for a in summary)
    fig.text(0.05, 0.665, f"Dylan Layden  —  {names}", fontproperties=sans, fontsize=15, color=INK2)
    fig.add_artist(plt.Line2D([0.05, 0.95], [0.615, 0.615], color=RULE, lw=1.2))

    apps = [a for a in summary if a.get("preview")][:4]
    w, gap, x0 = 0.2, 0.0333, 0.05
    for i, a in enumerate(apps):
        pv = a["preview"]
        left = x0 + i * (w + gap)
        title = {"Housing & SF Real Estate": "Housing"}.get(a["name"], a["name"].split(" · ")[0])
        fig.text(left, 0.555, title, fontproperties=serif, fontsize=16, color=INK)
        fig.text(left, 0.515, pv["caption"].replace(", trailing four quarters", " (trailing 4Q)"),
                 fontproperties=sans, fontsize=10.5, color=MUTED)
        ax = fig.add_axes([left + 0.034, 0.1, w - 0.044, 0.34], facecolor=BG)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(RULE)
        ax.tick_params(colors=MUTED, labelsize=9, length=0)
        ax.grid(axis="y", color=GRID, lw=1)
        ax.set_axisbelow(True)
        if pv["kind"] == "flow":
            ax.set_position([left, 0.1, w, 0.34])
            tot = sum(d["value"] for d in pv["demand"])
            rows = sorted(pv["demand"], key=lambda d: d["value"])
            shares = [d["value"] / tot * 100 for d in rows]
            ax.barh(range(len(rows)), shares, color=S1, height=0.5)
            for j, (d, v) in enumerate(zip(rows, shares)):
                ax.text(v + 1.2, j, f"{d['label'].replace(' & unreported', ' & other')}  {v:.0f}%",
                        va="center", fontproperties=sans, fontsize=10, color=INK2)
            ax.set_xlim(0, 75)
            ax.set_yticks([])
            ax.set_xticks([])
            ax.grid(False)
            continue
        for k, ser in enumerate(pv["series"][:2]):
            if pv["kind"] == "curve":
                xs = [math.log(v) for v in ser["x"]]
            else:
                xs = [dt.date.fromisoformat(d).toordinal() for d in ser["x"]]
            ax.plot(xs, ser["y"], color=(S1, S2)[k], lw=2.4 if k == 0 else 2, label=ser["label"])
        if len(pv["series"]) > 1:
            leg = ax.legend(loc="lower left", bbox_to_anchor=(-0.17, 1.02), frameon=False, prop=sans,
                            labelcolor=INK2, handlelength=1.4, ncols=2, borderaxespad=0, columnspacing=1.2)
            for t in leg.get_texts():
                t.set_fontsize(10)
        if pv["kind"] == "curve":
            tv, tt = pv["ticks"]["vals"], pv["ticks"]["text"]
            keep = [j for j, t in enumerate(tt) if t in ("3M", "2Y", "10Y", "30Y")]
            ax.set_xticks([math.log(tv[j]) for j in keep], [tt[j] for j in keep])
        else:
            xs0 = [dt.date.fromisoformat(d) for d in pv["series"][0]["x"]]
            ax.set_xticks([xs0[0].toordinal(), xs0[-1].toordinal()], [str(xs0[0].year), str(xs0[-1].year)])
        if pv["fmt"] == "pct":
            ax.yaxis.set_major_formatter(lambda v, _: f"{v:g}%")
        ax.locator_params(axis="y", nbins=4)
    asof = dt.datetime.fromisoformat(NOW).astimezone().strftime("%b %-d, %Y")
    fig.text(0.95, 0.03, f"Data as of {asof} · public sources · refreshed daily", fontproperties=sans,
             fontsize=10, color=MUTED, ha="right")
    fig.savefig(SITE / "og.png", facecolor=BG)
    plt.close(fig)


SECRET_PATTERNS = [
    re.compile(r"(?i)api[_-]?key=[A-Za-z0-9]{8,}"),
    re.compile(r"(?i)(token|secret|password)[\"']?\s*[:=]\s*[\"'][^\"']{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def secret_scan() -> list[str]:
    """Return offending paths only — never matched values."""
    known = []
    settings = Path.home() / ".openbb_platform" / "user_settings.json"
    try:
        creds = json.loads(settings.read_text()).get("credentials", {})
        known = [v for v in creds.values() if isinstance(v, str) and len(v) >= 8]
    except Exception:  # noqa: BLE001
        pass
    bad = []
    for p in SITE.rglob("*"):
        if not p.is_file():
            continue
        text = p.read_text(errors="ignore")
        if any(k in text for k in known) or any(rx.search(text) for rx in SECRET_PATTERNS):
            bad.append(str(p.relative_to(SITE)))
    return bad


NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def main() -> int:
    t0 = time.time()
    widgets = get_json("/widgets.json")
    apps = {a["name"]: a for a in get_json("/apps.json")}
    missing = [c["name"] for c in SHOWCASE if c["name"] not in apps]
    if missing:
        log("missing apps on backend:", missing)
        return 2

    # Static shell: refresh from ./web every build; data dir is updated in place so
    # stale-but-real payloads survive a failed fetch.
    SITE.mkdir(exist_ok=True)
    for item in WEB.iterdir():
        dest = SITE / item.name
        if item.is_dir():
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    (SITE / ".nojekyll").write_text("")

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        summary = [build_app(c, widgets, apps, ex) for c in SHOWCASE]

    (DATA / "index.json").write_text(json.dumps({"generated_at": NOW, "apps": summary,
                                                 "sources": source_names(SHOWCASE)}, indent=1))
    build_og(summary)

    bad = secret_scan()
    if bad:
        log("SECRET SCAN FAILED — do not publish. Paths:", bad)
        return 3

    size = sum(p.stat().st_size for p in SITE.rglob("*") if p.is_file())
    failed = sum(a["failed"] for a in summary)
    log(f"built {SITE} in {time.time() - t0:.0f}s — {size / 1e6:.1f} MB, "
        f"{sum(a['ok'] for a in summary)} payloads, {failed} failed, secret scan clean")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
