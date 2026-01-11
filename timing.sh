# timing.sh
# Marks-only JSONL logger (one JSON object per line)

set -euo pipefail

: "${TIMING_LOG:=timings.jsonl}"

: "${TIMING_REPO:=}"
: "${TIMING_BRANCH:=}"
: "${TIMING_CYCLE_ID:=}"
: "${TIMING_EXPERIMENT_ID:=}"
: "${TIMING_PHASE:=}"

: "${TIMING_HOST:=$(hostname 2>/dev/null || echo unknown)}"

_now_utc() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }

_json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  s="${s//$'\t'/\\t}"
  printf '%s' "$s"
}

timing_mark() {
  # Usage: timing_mark "start_pydeps" ["optional freeform note"]
  local event="$1"
  local note="${2:-}"
  local ts; ts="$(_now_utc)"

  mkdir -p "$(dirname "$TIMING_LOG")" 2>/dev/null || true

  printf '{' >> "$TIMING_LOG"
  printf '"ts_utc":"%s",' "$ts" >> "$TIMING_LOG"
  printf '"type":"mark",' >> "$TIMING_LOG"
  printf '"event":"%s",' "$(_json_escape "$event")" >> "$TIMING_LOG"
  printf '"note":"%s",' "$(_json_escape "$note")" >> "$TIMING_LOG"
  printf '"repo":"%s",' "$(_json_escape "$TIMING_REPO")" >> "$TIMING_LOG"
  printf '"branch":"%s",' "$(_json_escape "$TIMING_BRANCH")" >> "$TIMING_LOG"
  printf '"cycle_id":"%s",' "$(_json_escape "$TIMING_CYCLE_ID")" >> "$TIMING_LOG"
  printf '"experiment_id":"%s",' "$(_json_escape "$TIMING_EXPERIMENT_ID")" >> "$TIMING_LOG"
  printf '"phase":"%s",' "$(_json_escape "$TIMING_PHASE")" >> "$TIMING_LOG"
  printf '"host":"%s",' "$(_json_escape "$TIMING_HOST")" >> "$TIMING_LOG"
  printf '"pid":%d' "$$" >> "$TIMING_LOG"
  printf '}\n' >> "$TIMING_LOG"
}
