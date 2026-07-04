#!/bin/bash
# Daily job: refresh tonight's stage data, then commit + push so Vercel redeploys.
# Called by launchd (com.growthmedium.tdf-daily). Safe to run manually.
set -u
export PATH="/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:$PATH"
cd "$HOME/tour-de-france-2026" || exit 1

# 1) regenerate stage-today.js (deterministic pick + spoiler-safe AI enrichment)
/usr/bin/python3 tools/update_stage.py "$@"

# 2) publish if anything changed (only if this is a git repo with a remote)
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git remote get-url origin >/dev/null 2>&1; then
    git add stage-today.js data.js tdf_data.json 2>/dev/null
    if ! git diff --cached --quiet; then
      git commit -m "chore: daily TdF update — $(date '+%Y-%m-%d %H:%M %Z')" >/dev/null
      if git push origin HEAD >/dev/null 2>&1; then
        echo "[publish] pushed — Vercel will redeploy"
      else
        echo "[publish] push failed (check auth / network)" >&2
      fi
    else
      echo "[publish] no changes to publish"
    fi
  else
    echo "[publish] no git remote 'origin' yet — skipping push"
  fi
fi
