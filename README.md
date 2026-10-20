# Markets Research Terminal: public snapshot

A read-only, daily-refreshed static website of research dashboards on macro, housing, gold,
and credit and debt. Live at **https://dylanlayden.github.io/markets/**.

The dashboards are computed by a private Python/FastAPI analytics backend (originally served
into OpenBB Workspace). This repo holds only the snapshot tooling and the front end. No
backend code, credentials or private data are in it.

## How it works

```
local FastAPI backend (:6901)  ──>  build_site.py  ──>  site/  ──>  publish.sh  ──>  gh-pages
  /widgets.json, /apps.json          fetch every tile,          static HTML + JSON     GitHub Pages
  chart / table / markdown           pre-render dropdowns,
                                     secret-scan the output
```

- `build_site.py` reads the backend's widget and app manifests, fetches every tile of the
  showcase apps (all option combinations for dropdown params), validates each payload's
  shape, and writes `site/`. A tile whose fetch fails keeps its previous snapshot and is
  marked *stale*. The output is scanned for credentials before the build reports success.
- `web/` is the front end: a 40-column grid matching the original Workspace layout, lazy
  tile loading, Plotly charts, sortable tables, and sanitized Markdown. Libraries load from
  jsDelivr, pinned and with SRI hashes.
- `publish.sh` force-pushes `site/` to `gh-pages` as a single commit, so history never grows.
- `refresh.sh` is the daily job: it checks backend health, builds and publishes.

## Run

```bash
python build_site.py            # needs the backend on 127.0.0.1:6901
python -m http.server 8765 --directory site
./publish.sh                    # or ./refresh.sh for build + publish
```

Edit `SHOWCASE` in `build_site.py` to change which dashboards are published.

## Data

Each dashboard credits its sources on the page. The data comes from public providers
(FRED, Federal Reserve, New York Fed, U.S. Treasury Fiscal Data, BIS, CFTC, Zillow Research,
Redfin Data Center, World Gold Council, LBMA, Yahoo Finance; curated tables from S&P Global
Ratings' annual default study) and remains subject to their terms. It is shown
for research and educational purposes only and is not investment advice.
