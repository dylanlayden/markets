#!/usr/bin/env bash
# Daily job (LaunchAgent co.dylanlayden.markets-site): rebuild the snapshot from the
# local backend and publish it. Skips publishing if the backend is down or the
# build fails, so the live site keeps the last good snapshot.
set -uo pipefail
cd "$(dirname "$0")"
PY=/Users/dylanlayden/anaconda3/envs/openbb/bin/python
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

echo "=== $(date) refresh start"
if ! curl -fsS -m 10 http://127.0.0.1:6901/healthz >/dev/null; then
  echo "backend not healthy; skipping"; exit 0
fi
$PY build_site.py
rc=$?
if [ $rc -ne 0 ] && [ $rc -ne 1 ]; then
  echo "build failed (rc=$rc); not publishing"; exit $rc
fi
# rc=1 means some tiles failed but the rest built; publish anyway (failed tiles keep the last snapshot)
./publish.sh
echo "=== $(date) refresh done (build rc=$rc)"
