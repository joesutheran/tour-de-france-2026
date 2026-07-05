#!/usr/bin/env python3
"""
Daily updater for the Tour de France 2026 home page.

Works out, for the current New Zealand date, which stage's highlights to watch
*tonight* (NZ evening) and which stage is racing *overnight* tonight, then writes
`stage-today.js` next to index.html.

Timing model (confirmed): NZ is +10h ahead of France (CEST) during the Tour.
A stage raced on European date D finishes in NZ's small hours of D+1, so its
highlights are watched on the NZ evening of D+1.

    tonight's highlights  = stage whose European date == (NZ today - 1 day)
    racing overnight      = stage whose European date ==  NZ today

The stage selection is deterministic. When the race is on, an optional `claude -p`
step then adds spoiler-safe context (a tactical preview, the standings entering
tonight's stage, and the DNF list) — see the AI-enrichment section below. Pass
`--no-ai` for the deterministic-only path.

Python 3.9 compatible. No `X | Y` unions.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_PATH = os.path.join(ROOT, "tdf_data.json")
OUT_PATH = os.path.join(ROOT, "stage-today.js")

NZ = ZoneInfo("Pacific/Auckland")

# Daily flip hour (NZ). Below this hour the page shows "Start of Stage X"; at/after
# it, once you've watched, it flips to "End of Stage X" and rolls the page forward.
# The browser reads this from the payload's `boundary_hour`, so this constant is the
# single source of truth for the flip. The scheduler (n8n cron + the launchd fallback
# plist) must fire at this same hour — see README "Triggering the daily update".
BOUNDARY_HOUR = 10


def load_data() -> Dict[str, Any]:
    with open(DATA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _dated(stages) -> List[Dict[str, Any]]:
    return [s for s in stages if s.get("date") and s.get("num") is not None]


def latest_on_or_before(stages, iso: str) -> Optional[Dict[str, Any]]:
    best = None
    for s in _dated(stages):
        if s["date"] <= iso and (best is None or s["date"] > best["date"]):
            best = s
    return best


def earliest_on_or_after(stages, iso: str) -> Optional[Dict[str, Any]]:
    best = None
    for s in _dated(stages):
        if s["date"] >= iso and (best is None or s["date"] < best["date"]):
            best = s
    return best


def build_payload(data: Dict[str, Any], now_nz: datetime) -> Dict[str, Any]:
    """State as of the daily flip (BOUNDARY_HOUR, NZ).

    Before the flip the page shows the stage you're about to watch this cycle
    ("Start of Stage K"). At the flip — once you've watched — it reveals that
    stage's result ("End of Stage K") and rolls the hero forward to the next
    stage. So this payload is the AFTER-watching state:
      * standings reflect the END of the just-watched stage;
      * the hero previews the NEXT stage to watch (spoiler-free).
    End-of-stage-K == start-of-stage-(K+1), so one file generated at the flip
    also serves the next pre-flip window — the browser just relabels
    'End of Stage K' -> 'Start of Stage K+1' and never has to reveal an unwatched
    result, because the result only enters the file at the flip when you watch it.
    """
    stages = data.get("stages", [])
    nz_today = now_nz.date()

    # Time-aware boundary (mirrors the browser). Before the flip the live state is
    # still the previous cycle's (you haven't watched this cycle's stage yet), so
    # anchor to yesterday; at/after the flip, roll forward to today. Whenever this
    # runs it emits exactly the file correct for that moment — and that file also
    # serves the following pre-flip window, since the browser resolves the same ref.
    after_flip = now_nz.hour >= BOUNDARY_HOUR
    ref_date = nz_today if after_flip else (nz_today - timedelta(days=1))
    ref_iso = ref_date.isoformat()
    prev_iso = (ref_date - timedelta(days=1)).isoformat()

    watched = latest_on_or_before(stages, prev_iso)     # standings reflect the END of this stage
    preview = earliest_on_or_after(stages, ref_iso)     # next stage to watch (hero)

    if watched is None and preview is not None:
        status = "pre-race"
    elif preview is None:
        status = "finished"
    else:
        status = "racing"

    return {
        "generated_at": now_nz.isoformat(),
        "nz_date": nz_today.isoformat(),
        "as_of_date": ref_iso,
        "boundary_hour": BOUNDARY_HOUR,
        "status": status,
        # just-watched stage — standings below are its END classifications
        "watched": ({"num": watched.get("num"), "date": watched.get("date")} if watched else None),
        # next stage to watch — full object; AI merges fresh spoiler-free preview text
        "preview": preview,
        "abandoned": [],
    }


def write_js(payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    js = (
        "// Auto-generated by tools/update_stage.py — do not edit by hand.\n"
        "// Regenerated daily. If this file is missing or stale, index.html falls\n"
        "// back to computing tonight's stage in the browser from the embedded schedule.\n"
        "window.STAGE_TODAY = " + body + ";\n"
    )
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(js)


# ----------------------------------------------------------------------------
# AI enrichment — spoiler-safe daily research via `claude -p`
#
# THE SPOILER BOUNDARY (critical): tonight we watch highlights of stage K. We
# have already watched everything up to and including stage K-1. So the job may
# ONLY use information current as of the START of stage K (= end of stage K-1):
#   - standings AFTER stage K-1  (= the numbers riders START stage K with)
#   - abandonments THROUGH stage K-1 only
#   - a tactical PREVIEW of stage K written from that pre-stage picture — never
#     its result. The model is told not to look up stage K at all.
# ----------------------------------------------------------------------------

def find_claude() -> Optional[str]:
    cand = shutil.which("claude")
    if cand:
        return cand
    for p in ("~/.claude/local/claude", "~/.local/bin/claude",
              "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        p = os.path.expanduser(p)
        if os.path.exists(p):
            return p
    return None


def roster_block(data: Dict[str, Any]) -> str:
    lines = []  # type: List[str]
    for t in data.get("teams", []):
        leader = t.get("road_leader") or ""
        names = []
        for r in t.get("riders", []):
            tag = " [LEADER]" if leader and r.get("name") and r["name"] in leader else ""
            names.append("%s (%s)%s" % (r.get("name", "?"), r.get("specialty", "?"), tag))
        lines.append("%s — %s" % (t.get("team_name", "?"), "; ".join(names)))
    return "\n".join(lines)


def build_prompt(data: Dict[str, Any], payload: Dict[str, Any]) -> str:
    W = payload.get("watched") or {}      # stage just watched — standings reflect its END
    P = payload.get("preview") or {}      # next stage to watch — the spoiler-free preview
    Wn = W.get("num")
    Pn = P.get("num")
    race = data.get("race", {})
    profile = "%s, %s km, ~%s m climbing%s" % (
        P.get("type", "?"), P.get("distance_km", "?"), P.get("climb_m", "?"),
        ", SUMMIT FINISH" if P.get("summit_finish") else "")

    if Wn:
        watched_line = ("They have just watched STAGE %d tonight, and have seen every stage up to and "
                        "including it." % Wn)
        boundary = ("You may ONLY use information current as of the END of stage %d. NEVER look up, infer "
                    "or reveal the result of stage %d (the preview stage) or anything after it. Do NOT "
                    "search for 'stage %d result/winner' — if a result for stage %d or later appears, "
                    "IGNORE it completely." % (Wn, Pn, Pn, Pn))
        standings_ask = (
            "Fetch these four classifications AS THEY STAND AFTER STAGE %d (the stage the couple just "
            "watched), EACH as a top-10 table: (1) General Classification with time gaps; (2) Points / "
            "Green jersey with points totals; (3) Mountains / Polka-dot (KOM) with points totals; "
            "(4) Young rider / White jersey with time gaps." % Wn)
        abandon_ask = ("Also compile the riders who have ABANDONED / been eliminated / did-not-start "
                       "THROUGH stage %d (web search: 'Tour de France 2026 abandons / non-starters')." % Wn)
    else:
        watched_line = "The race has not started yet — no stage has been watched."
        boundary = ("The race has NOT started. NEVER look up, infer or reveal the result of stage %d "
                    "(the preview stage) or anything after it." % Pn)
        standings_ask = ("There are no standings yet — the race has not started. Return EMPTY arrays for "
                         "all four classifications.")
        abandon_ask = "There are no abandonments yet — return an empty array."

    return (
        "You are the spoiler-safe race desk for a couple in New Zealand who watch Tour de France "
        "highlights at about 7pm their time. %s You are preparing what they see AFTER tonight's viewing: "
        "the up-to-date classifications, and a preview of the NEXT stage they'll watch.\n\n"
        "ABSOLUTE SPOILER RULE — break this and you ruin their night:\n  * %s\n\n"
        "NEXT STAGE TO PREVIEW — STAGE %s: %s -> %s. Profile: %s.\n"
        "Race context: %s.\n\n"
        "%s\n\n"
        "%s Use rider names spelled EXACTLY as they appear in this startlist so they can be matched:\n%s\n\n"
        "Now write a rich, SPOILER-FREE 'what to watch for' preview of STAGE %s (4-6 sentences). Make it "
        "tactically specific and rider-aware, grounded in the classifications above and each rider's real "
        "situation — e.g. a GC contender down on time who must attack; a renowned descender who will chance "
        "a move on a technical descent; a sprinter's team needing to control a flat day; a summit finish "
        "suiting the pure climbers. Name specific riders and WHY the profile plus their position makes them "
        "act. Do NOT state or hint at any result.\n\n"
        "Return ONLY a single JSON object, no prose, of exactly this shape:\n"
        "{\"preview_watch_for\":\"...\",\"preview_riders_to_watch\":[\"Name\",...],"
        "\"standings\":{"
        "\"gc\":[{\"rank\":1,\"rider\":\"...\",\"team\":\"...\",\"gap\":\"race lead\"}],"
        "\"points\":[{\"rank\":1,\"rider\":\"...\",\"team\":\"...\",\"pts\":123}],"
        "\"kom\":[{\"rank\":1,\"rider\":\"...\",\"team\":\"...\",\"pts\":45}],"
        "\"youth\":[{\"rank\":1,\"rider\":\"...\",\"team\":\"...\",\"gap\":\"race lead\"}]},"
        "\"abandoned\":[{\"name\":\"Exact Name\",\"stage\":<int>,\"reason\":\"...\"}],"
        "\"confidence\":\"high|medium|low\",\"sources\":[\"url\"]}"
        % (watched_line, boundary, Pn, P.get("start", "?"), P.get("finish", "?"), profile,
           race.get("overview", ""), standings_ask, abandon_ask, roster_block(data), Pn))


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    # try whole thing, then the last balanced object
    try:
        return json.loads(text)
    except Exception:
        pass
    depth = 0
    start = -1
    best = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                chunk = text[start:i + 1]
                try:
                    best = json.loads(chunk)
                except Exception:
                    pass
    return best


def run_ai(data: Dict[str, Any], payload: Dict[str, Any], timeout: int,
           model: Optional[str] = None) -> Optional[Dict[str, Any]]:
    claude = find_claude()
    if not claude:
        print("[update_stage] claude binary not found — skipping AI enrichment", file=sys.stderr)
        return None
    prompt = build_prompt(data, payload)
    cmd = [claude, "-p", prompt, "--output-format", "json", "--allowedTools", "WebSearch"]
    # The research is web-search + extraction, not deep reasoning — a fast model does
    # it in a fraction of the time. The default Opus-class model was timing out.
    if model:
        cmd += ["--model", model]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    except subprocess.TimeoutExpired:
        print("[update_stage] AI enrichment timed out after %ss — using base payload" % timeout, file=sys.stderr)
        return None
    except Exception as e:  # noqa
        print("[update_stage] AI enrichment error: %s" % e, file=sys.stderr)
        return None
    out = res.stdout or ""
    wrapper = None
    try:
        wrapper = json.loads(out)
    except Exception:
        wrapper = None
    text = wrapper.get("result", out) if isinstance(wrapper, dict) else out
    ai = extract_json(text)
    if not ai:
        print("[update_stage] could not parse AI JSON — using base payload", file=sys.stderr)
        return None
    return ai


def merge_ai(payload: Dict[str, Any], ai: Dict[str, Any]) -> None:
    p = payload.get("preview")
    if p:
        if ai.get("preview_watch_for"):
            p["watch_for"] = ai["preview_watch_for"]
            p["contextual"] = True
        if ai.get("preview_riders_to_watch"):
            p["riders_to_watch"] = ai["preview_riders_to_watch"]
    w = payload.get("watched") or {}
    st = ai.get("standings")
    if isinstance(st, dict) and st.get("gc"):
        # tag which stage boundary these standings are AFTER, so the browser can
        # verify freshness and pick the right 'Start of' / 'End of' label.
        st["after_stage_num"] = w.get("num")
        st["after_stage_date"] = w.get("date")
        payload["standings"] = st
    ab = ai.get("abandoned")
    if isinstance(ab, list):
        # SPOILER SAFETY NET: never surface a DNF from a stage they haven't watched
        # yet — only through the just-watched stage (Wn).
        Wn = w.get("num")
        if isinstance(Wn, int):
            ab = [a for a in ab if not (isinstance(a.get("stage"), int) and a["stage"] > Wn)]
        payload["abandoned"] = ab
    payload["ai"] = {"confidence": ai.get("confidence"), "sources": ai.get("sources", [])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ai", action="store_true", help="skip claude enrichment (deterministic only)")
    # Fetching four real classifications + DNFs via live web search takes several
    # minutes; 300s times out once actual standings exist (not just pre-race empties).
    ap.add_argument("--timeout", type=int, default=900, help="claude -p timeout seconds")
    # Fast model for the research call — Opus-class defaults were timing out.
    ap.add_argument("--model", default="sonnet", help="model for claude -p enrichment ('' = CLI default)")
    a = ap.parse_args()

    now_nz = datetime.now(NZ)
    data = load_data()
    payload = build_payload(data, now_nz)

    if not a.no_ai and payload.get("preview") and payload.get("status") != "finished":
        ai = run_ai(data, payload, a.timeout, model=(a.model or None))
        if ai:
            merge_ai(payload, ai)
            print("[update_stage] AI enrichment merged (%d GC rows, %d abandoned)" % (
                len((payload.get("standings") or {}).get("gc", [])),
                len(payload.get("abandoned", []))))

    write_js(payload)
    p = payload.get("preview")
    label = ("Stage %s (%s)" % (p["num"], p.get("type", "")) if p else "nothing")
    print("[update_stage] NZ %s (run at %s) -> next to watch: %s | standings after Stage %s [status=%s]" % (
        payload["nz_date"], now_nz.strftime("%H:%M %Z"), label,
        (payload.get("watched") or {}).get("num"), payload["status"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
