#!/usr/bin/env bash
set -euo pipefail

# ── Add scorer package to Python path ────────────────────────────────
export PYTHONPATH="${SCORER_PATH}:${PYTHONPATH:-}"

# ── Inputs from action.yml (passed via env) ──────────────────────────
DIRECTORY="${INPUT_DIRECTORY:-.}"
BATCH="${INPUT_BATCH:-false}"
THRESHOLD="${INPUT_THRESHOLD:-70}"
ONLY_CHANGED="${INPUT_ONLY_CHANGED:-false}"
BASE_SHA="${INPUT_BASE_SHA:-}"
HEAD_SHA="${INPUT_HEAD_SHA:-}"
FAIL_BELOW="${INPUT_FAIL_BELOW_THRESHOLD:-true}"

REPORT_FILE="$(mktemp /tmp/codebundle-score-XXXXXX)"
RESULTS_JSON="$(mktemp /tmp/codebundle-results-XXXXXX)"

# ── Helper: find changed CodeBundles ─────────────────────────────────
find_changed_bundles() {
  local base="$1" head="$2" dir="$3"
  git diff --name-only "$base" "$head" \
    | grep '\.robot$\|generation-rules\|templates/\|README\.md$' \
    | while IFS= read -r f; do
        bundle_dir="$(dirname "$f")"
        while [ "$bundle_dir" != "." ] && [ "$bundle_dir" != "/" ]; do
          if [ -f "$bundle_dir/runbook.robot" ]; then
            echo "$bundle_dir"
            break
          fi
          bundle_dir="$(dirname "$bundle_dir")"
        done
      done \
    | sort -u
}

# ── Determine which bundles to score ─────────────────────────────────
declare -a BUNDLES=()

if [ "$ONLY_CHANGED" = "true" ] && [ -n "$BASE_SHA" ] && [ -n "$HEAD_SHA" ]; then
  echo "::group::Detecting changed CodeBundles"
  while IFS= read -r b; do
    [ -n "$b" ] && BUNDLES+=("$b")
  done < <(find_changed_bundles "$BASE_SHA" "$HEAD_SHA" "$DIRECTORY")
  echo "Found ${#BUNDLES[@]} changed CodeBundle(s)"
  printf '  - %s\n' "${BUNDLES[@]}"
  echo "::endgroup::"
elif [ "$BATCH" = "true" ]; then
  echo "::group::Discovering CodeBundles in $DIRECTORY"
  for d in "$DIRECTORY"/*/; do
    [ -f "$d/runbook.robot" ] && BUNDLES+=("${d%/}")
  done
  echo "Found ${#BUNDLES[@]} CodeBundle(s)"
  echo "::endgroup::"
else
  BUNDLES+=("$DIRECTORY")
fi

if [ "${#BUNDLES[@]}" -eq 0 ]; then
  echo "No CodeBundles to score."
  echo "total_scored=0" >> "$GITHUB_OUTPUT"
  echo "total_passed=0" >> "$GITHUB_OUTPUT"
  echo "total_failed=0" >> "$GITHUB_OUTPUT"
  echo "report_file=" >> "$GITHUB_OUTPUT"
  echo "report_markdown=" >> "$GITHUB_OUTPUT"
  exit 0
fi

# ── Score each bundle ────────────────────────────────────────────────
TOTAL=0
PASSED=0
FAILED=0
ALL_REPORTS=""

for bundle in "${BUNDLES[@]}"; do
  echo "::group::Scoring $(basename "$bundle")"
  TOTAL=$((TOTAL + 1))

  REPORT="$(python -m scorer.score "$bundle" --threshold "$THRESHOLD" --format markdown 2>&1)" || true

  SCORE_LINE="$(echo "$REPORT" | head -1)"
  if echo "$REPORT" | grep -q '(PASS)'; then
    PASSED=$((PASSED + 1))
    echo "✅ $SCORE_LINE"
  else
    FAILED=$((FAILED + 1))
    echo "❌ $SCORE_LINE"
  fi

  ALL_REPORTS="${ALL_REPORTS}${REPORT}

---

"
  echo "::endgroup::"
done

# ── Build aggregate report ───────────────────────────────────────────
{
  echo "# CodeBundle Score Report"
  echo ""
  echo "| Metric | Value |"
  echo "|--------|-------|"
  echo "| Scored | $TOTAL |"
  echo "| Passed | $PASSED |"
  echo "| Failed | $FAILED |"
  echo "| Threshold | $THRESHOLD |"
  echo ""
  echo "---"
  echo ""
  echo "$ALL_REPORTS"
} > "$REPORT_FILE"

# ── Set outputs ──────────────────────────────────────────────────────
echo "total_scored=$TOTAL" >> "$GITHUB_OUTPUT"
echo "total_passed=$PASSED" >> "$GITHUB_OUTPUT"
echo "total_failed=$FAILED" >> "$GITHUB_OUTPUT"
echo "report_file=$REPORT_FILE" >> "$GITHUB_OUTPUT"

{
  echo "report_markdown<<REPORT_EOF"
  cat "$REPORT_FILE"
  echo "REPORT_EOF"
} >> "$GITHUB_OUTPUT"

# ── Exit code ────────────────────────────────────────────────────────
if [ "$FAIL_BELOW" = "true" ] && [ "$FAILED" -gt 0 ]; then
  echo ""
  echo "::error::$FAILED of $TOTAL CodeBundle(s) scored below threshold ($THRESHOLD)."
  exit 1
fi
