#!/usr/bin/env bash
#
# Runs the full research loop once, headless, before the US open.
#
# Claude reads the sentiment-trading-loop skill from .claude/skills/, calls the Apify
# Actor through the MCP server, builds the day's watchlist, and arms the simulator.
# Scheduling is left to cron or launchd — see the README.
#
# Nothing here holds a credential. The Apify token lives in your MCP configuration;
# this script never sees it.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/$(date +%Y-%m-%d).log"

CAPITAL="${CAPITAL:-1000}"
PORT="${PORT:-8777}"

cd "${REPO_DIR}"

{
  echo "=== $(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z') — starting morning run ==="

  # Weekends have no session. Holidays are handled by the engine, which simply never
  # leaves the 'armed' state.
  DOW="$(TZ=America/New_York date +%u)"
  if [ "${DOW}" -gt 5 ]; then
    echo "Weekend — nothing to do."
    exit 0
  fi

  if ! command -v claude >/dev/null 2>&1; then
    echo "ERROR: the 'claude' CLI is not on PATH. Install Claude Code first." >&2
    exit 1
  fi

  claude -p "Run the sentiment-trading-loop skill end to end for today's US session. \
Collect a fresh sweep from the Apify Actor, extract and validate tickers, build the \
50-name watchlist, freeze it into marketsim/sessions/<today>/, and leave the simulator \
armed with \$${CAPITAL} on port ${PORT}. Report the watchlist buckets and the session \
drivers when you are done." \
    --permission-mode acceptEdits

  echo "=== finished at $(TZ=America/New_York date '+%H:%M:%S %Z') ==="
} 2>&1 | tee -a "${LOG_FILE}"
