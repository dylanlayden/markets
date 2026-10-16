#!/usr/bin/env bash
# Publish ./site to the gh-pages branch as a single orphan commit (force-push),
# so daily data refreshes never accumulate history.
set -euo pipefail
cd "$(dirname "$0")"

REMOTE="$(git remote get-url origin)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp -R site/. "$STAGE/"
cd "$STAGE"
git init -q -b gh-pages
git config user.name "$(git -C "$OLDPWD" config user.name)"
git config user.email "$(git -C "$OLDPWD" config user.email)"
git config credential.helper "!gh auth git-credential"
# ~11 MB push: git's 1 MB default buffer switches to chunked encoding, which GitHub
# can reject with HTTP 400. Send it in one request instead.
git config http.postBuffer 157286400
# Large pushes over HTTP/2 also hit the same 400 from GitHub; HTTP/1.1 avoids it.
git config http.version HTTP/1.1
git add -A
git commit -q -m "Snapshot $(date -u +%Y-%m-%dT%H:%MZ)"
git push -q --force "$REMOTE" gh-pages
echo "published $(du -sh . | cut -f1) to gh-pages"
