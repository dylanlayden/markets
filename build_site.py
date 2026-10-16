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

# Showcase apps, in display order: the rates/credit and real-estate views lead, crypto
# comes last. Silver Market is held back: its core tiles are derived from the World
# Silver Survey (licensed publication).
SHOWCASE = [
    {
        "name": "Macro Factors",
        "slug": "macro",
        "blurb": "US rates, credit, inflation, growth, labor and global yields — 20 charts with recession shading.",
        "sources": "FRED (Federal Reserve Bank of St. Louis) via OpenBB Platform; NBER recession dates.",
        "preview": {"tile": "macro_credit_spreads", "fmt": "pct",
                    "series": [["US High Yield", "High yield"], ["US Investment Grade", "Investment grade"]],
                    "caption": "US corporate option-adjusted spreads, %"},
    },
    {
        "name": "Housing & SF Real Estate",
        "slug": "housing",
        "blurb": "US housing macro down to San Francisco ZIP codes: prices, momentum, rents and gross yields.",
        "sources": "FRED (S&P CoreLogic Case-Shiller, Realtor.com, Freddie Mac, BLS); Zillow Research (ZHVI, ZORI); Redfin Data Center.",
        "preview": {"tile": "re_sf_caseshiller", "fmt": "index",
                    "series": [["Case-Shiller SF", "San Francisco"]],
                    "caption": "S&P CoreLogic Case-Shiller San Francisco home price index (Jan 2000 = 100)"},
    },
    {
        "name": "Gold Market",
        "slug": "gold",
        "blurb": "Gold supply and demand, central-bank buying, ETF flows, futures positioning and producers.",
        "sources": "World Gold Council (Goldhub); LBMA; CFTC; Yahoo Finance.",
        "preview": {"tile": "gd_aisc", "fmt": "usd",
                    "series": [["Gold price (quarterly avg)", "Gold price"], ["All-in sustaining cost", "Miners' all-in cost"]],
                    "caption": "Gold price vs producers' all-in sustaining cost, US$/oz, quarterly"},
    },
    {
        "name": "Gold Price Formation",
        "slug": "gold-price",
        "blurb": "Who sets the gold price: COT positioning, trader concentration, 13F holders and the COMEX–London basis.",
        "sources": "CFTC Commitments of Traders; SEC Form 13F data sets; LBMA; Yahoo Finance.",
        "preview": {"tile": "gp_cot_percentile", "fmt": "pct",
                    "series": [["Managed-money net long", "Managed money"]],
                    "caption": "COMEX gold managed-money net long, % of open interest, weekly"},
    },
    {
        "name": "HYPE · Hyperliquid Cash Flow",
        "slug": "hype",
        "blurb": "Hyperliquid valued as a cash-flowing asset: fees, revenue, buybacks, multiples and market structure.",
        "sources": "DefiLlama; Hyperliquid public info API; CoinGecko; OKX; FRED.",
        "preview": {"tile": "hy_fees_rev", "fmt": "usdm",
                    "series": [["Fees 30d avg", "Fees"], ["Revenue 30d avg", "Revenue"]],
                    "caption": "Hyperliquid daily fees and protocol revenue, 30-day average, US$"},
    },
]


PREVIEW_POINTS = 180   # homepage mini charts are downsampled to about this many points


def decode(v):
    """Plotly 6 ships arrays as {"dtype", "bdata"} (base64); expand to a plain list."""
    if isinstance(v, dict) and "bdata" in v:
        import base64, numpy as np
        return np.frombuffer(base64.b64decode(v["bdata"]), dtype=np.dtype(v["dtype"])).tolist()
    return v


def build_preview(cfg: dict, tiles: list[dict], outdir: Path) -> dict | None:
    """Small line series for the homepage card, taken from one of the app's own charts."""
    pc = cfg.get("preview")
    if not pc:
        return None
    try:
        tile = next(t for t in tiles if t["id"] == pc["tile"])
        fig = json.loads((outdir / tile["variants"][tile["default"]]).read_text())
        traces = {d.get("name"): d for d in fig["data"]}
        series = []
        for name, label in pc["series"]:
            d = traces[name]
            pts = [(str(x)[:10], y) for x, y in zip(decode(d["x"]), decode(d["y"]))
                   if isinstance(y, (int, float)) and y == y]
            step = max(1, -(-len(pts) // PREVIEW_POINTS))
            keep = pts[::step] if pts[::step][-1] == pts[-1] else pts[::step] + [pts[-1]]
            series.append({"label": label, "x": [p[0] for p in keep],
                           "y": [round(p[1], 4) for p in keep]})
        return {"caption": pc["caption"], "fmt": pc["fmt"], "tile": tile["name"], "series": series}
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
                q = dict(v)
                if wtype == "chart":
                    q["theme"] = "dark"
                jobs.append((tile, v, ex.submit(get_json, w["endpoint"], q)))

    ok = stale = failed = 0
    for tile, v, fut in jobs:
        fname = vfile(tile["id"], v)
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

    (DATA / "index.json").write_text(json.dumps({"generated_at": NOW, "apps": summary}, indent=1))

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
