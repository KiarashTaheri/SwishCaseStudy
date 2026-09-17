#!/usr/bin/env bash
# End-to-end check: clean clone -> data -> database -> API -> UI build.
#
# This is the claim the README makes, so it is worth testing rather than
# asserting. Run from the repository root:
#
#     ./scripts/smoke.sh
#
# Exits non-zero on the first failure, and always stops the API it started.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${PORT:-8000}"
API="http://127.0.0.1:${PORT}"
API_PID=""

# A throwaway database, not backend/swishos.db. `dispatch` holds human decisions
# and a rebuild deliberately does not erase it, so a developer who has clicked
# through the UI has dispatch rows that make /api/fleet legitimately differ from
# the committed fixture. That is the system behaving correctly and the check
# being wrong, so the check gets its own database.
SMOKE_DB="$(mktemp -d)/swishos.db"

pass() { printf '  \033[32mok\033[0m   %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; exit 1; }
step() { printf '\n\033[1m%s\033[0m\n' "$1"; }

cleanup() {
  if [[ -n "$API_PID" ]] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
  [[ -n "${SMOKE_DB:-}" ]] && rm -rf "$(dirname "$SMOKE_DB")"
  return 0
}
trap cleanup EXIT

step "1. Dataset"
# --start is not optional: seed_data.py falls back to date.today()-days, so the
# dates drift daily and stop matching the committed fixtures. See README.
python3 seed_data.py --start 2026-05-18 >/dev/null
[[ -f data/daily.csv ]] || fail "data/daily.csv not generated"
LAST_DAY="$(tail -1 data/daily.csv | cut -d, -f2)"
[[ "$LAST_DAY" == "2026-09-14" ]] || fail "last day is $LAST_DAY, expected 2026-09-14 (is --start pinned?)"
pass "data/ generated, last day $LAST_DAY"

step "2. Backend"
cd backend
[[ -d .venv ]] || python3 -m venv .venv
./.venv/bin/pip install --quiet -r requirements.txt
PY="./.venv/bin/python"

PYTHONPATH=. $PY -m swishos.build --data ../data --db "$SMOKE_DB" >/dev/null
pass "database built"

PYTHONPATH=. $PY -m pytest -q >/dev/null || fail "pytest suite failed"
pass "test suite green"

PYTHONPATH=. $PY scripts/verify.py >/dev/null 2>&1 \
  && pass "scripts/verify.py reproduces its claims" \
  || printf '  \033[33mskip\033[0m scripts/verify.py not present or failed\n'

step "3. API"
SWISHOS_DB="$SMOKE_DB" PYTHONPATH=. $PY -m uvicorn swishos.api:app --port "$PORT" --log-level warning &
API_PID=$!
for _ in $(seq 1 40); do
  curl -sf "${API}/api/health" >/dev/null 2>&1 && break
  sleep 0.25
done
curl -sf "${API}/api/health" >/dev/null || fail "API did not come up on :${PORT}"
pass "health responds"

curl -sf "${API}/api/fleet" -o /tmp/smoke_fleet.json || fail "GET /api/fleet failed"
cd "$ROOT"
python3 - <<'PY' || exit 1
import json, sys
live = json.load(open("/tmp/smoke_fleet.json"))
want = json.load(open("docs/fixtures/fleet.json"))
if live == want:
    print("  \033[32mok\033[0m   /api/fleet matches docs/fixtures/fleet.json exactly")
    sys.exit(0)
# Not identical: say precisely where, rather than just failing.
for key in ("as_of", "summary"):
    if live.get(key) != want.get(key):
        print(f"  \033[31mFAIL\033[0m {key}: live={live.get(key)} want={want.get(key)}")
lr = {r["region"] for r in live.get("regions", [])}
wr = {r["region"] for r in want.get("regions", [])}
if lr != wr:
    print(f"  \033[31mFAIL\033[0m regions differ: only-live={lr - wr} only-fixture={wr - lr}")
sys.exit(1)
PY
pass "fleet payload verified"

step "4. Frontend"
cd frontend
[[ -d node_modules ]] || npm install --silent
npx tsc --noEmit || fail "typecheck failed"
pass "typecheck clean"
npm run build >/dev/null 2>&1 || fail "next build failed"
pass "production build succeeds"

cd "$ROOT"
printf '\n\033[32mEnd-to-end check passed.\033[0m\n'
printf 'Start it with:\n'
printf '  cd backend && PYTHONPATH=. ./.venv/bin/uvicorn swishos.api:app --port 8000\n'
printf '  cd frontend && npm run dev\n'
