# Tour de France 2026 — home screen 🚴

A self-contained page for Joe & Fiona to follow the 2026 Tour from New Zealand.
Team cards (boss, road leader, every rider + specialty) and a **spoiler-free**
"what to watch tonight" section tuned for NZ-evening highlights viewing.

## Just watching?

Double-click **`index.html`**. That's it. It opens in your browser with no
internet needed.

The "Tonight's highlights" panel updates itself every day — the page works out,
from today's NZ date, which stage's highlights you'll be watching this evening
(the one raced overnight, European date = yesterday) and which stage is racing
overnight tonight. No results are ever shown: it's what to watch *for*, never
what happened.

Tip: drag `index.html` onto your browser toolbar / bookmark it, or right-click →
Open With → your browser, so it's one click each evening.

## How the daily update works

Two layers, so it can never break:

1. **Browser-side (always on).** `index.html` embeds the full schedule and
   spoiler-free notes and picks tonight's stage itself using the NZ clock. Open
   the file any evening and the right stage is already front-and-centre.

2. **Daily AI refresh job.** `tools/update_stage.py` runs on the launchd
   schedule. It (a) deterministically picks tonight's stage from the NZ clock,
   then (b) if the race is on, runs `claude -p` with web search to write a
   **contextual, rider-aware tactical preview**, the **standings** going into
   tonight's stage, and the **abandoned/DNF list** — all into `stage-today.js`,
   which the page prefers when present. If the AI step fails or times out, the
   page falls back to the embedded static notes, so it never breaks.

### The spoiler model (important)

Everything on the page is **frozen at the start of tonight's stage**. Tonight
you watch stage `K`; you have already watched stages up to `K-1`. So the job may
only ever use information current as of the *end of stage K-1*:

- **Standings** shown = classification after stage `K-1` (what riders start
  tonight's stage with) — never after stage `K`.
- **DNF/abandoned** riders shown = those out through stage `K-1` only. A
  deterministic guard also strips any DNF the model attributes to stage `K` or
  later.
- **Tactical preview** of stage `K` is written from that pre-stage picture and
  each rider's real characteristics/GC position — never its result.

Residual risk: the AI does live web search at ~14:00 NZ, by which time tonight's
stage has finished in Europe. The prompt forbids looking it up, and the guard
above filters DNFs, but if you ever spot a leaked result, run
`python3 tools/update_stage.py --no-ai` to fall back to the safe static notes.

### Timing model

NZ runs +10h ahead of France during the Tour. A stage raced on European date `D`
finishes in NZ's small hours of `D+1`, so:

- **Tonight's highlights** = the stage dated *yesterday* (Europe).
- **Racing overnight tonight** = the stage dated *today*.

## Files

| File | What it is |
|---|---|
| `index.html` | The page. Open this. |
| `tdf_data.json` | Single source of truth: race, teams, rosters, stages, watch notes. |
| `data.js` | `window.TDF = <tdf_data.json>` — what the page loads. |
| `stage-today.js` | Optional daily override written by the updater. |
| `tools/update_stage.py` | Daily updater — picks tonight's stage by NZ date. |
| `tools/com.growthmedium.tdf-daily.plist` | launchd job (daily 14:00 NZ). |

## Installing the daily job (launchd — recommended, local, reliable)

```sh
cp ~/tour-de-france-2026/tools/com.growthmedium.tdf-daily.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.growthmedium.tdf-daily.plist
# run it once now to generate stage-today.js:
launchctl kickstart gui/$(id -u)/com.growthmedium.tdf-daily
```

To stop it: `launchctl bootout gui/$(id -u)/com.growthmedium.tdf-daily`

## n8n option

n8n on Render can't write to this Mac's filesystem directly, so the clean n8n
path is: **n8n daily cron → HTTP GET the local webhook listener via the Tailscale
funnel → the listener runs `python3 tools/update_stage.py`.** That reuses the
existing `com.growthmedium.webhook-listener` service. Ask Claude to wire the
route + workflow (n8n changes need Joe's approval first). Until then, the launchd
job above covers the same job with fewer moving parts.

## Refreshing the data (rosters change during the Tour)

Edit `tdf_data.json` and regenerate `data.js`:

```sh
python3 -c "import json;open('/Users/joesutheran/tour-de-france-2026/data.js','w').write('window.TDF = '+open('/Users/joesutheran/tour-de-france-2026/tdf_data.json').read()+';')"
```
