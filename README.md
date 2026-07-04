# Tour de France 2026 — Spoiler-safe Highlights Companion 🚴

A self-contained web page for following the 2026 Tour **on highlights**, in a
timezone hours behind the racing (built and tuned for New Zealand evenings).
Team cards (boss, road leader, every rider + specialty on a horizontal slider),
jersey-filterable standings, and a **spoiler-free** "what to watch tonight"
panel — so you get all the context and none of the results before you've seen
the stage.

> **Spoiler-safe by design.** Everything on the page is frozen at the *start of
> the stage you're about to watch*: the standings, who's still in the race, and
> the tactical read all reflect the situation *entering* tonight's stage, never
> its outcome. See [The spoiler model](#the-spoiler-model-important).

## Just watching?

Open **`index.html`** in a browser — double-click the file, or visit the hosted
version if one is deployed (see [Hosting](#hosting-on-vercel)). No internet
needed for the local file.

The "Tonight's highlights" panel updates itself every day: the page works out,
from the current NZ date, which stage's highlights you'll be watching this
evening (the one raced overnight, European date = yesterday) and which stage is
racing overnight tonight. Click the jersey cards in **Standings** to switch the
table between the GC, points, mountains, and young-rider competitions.

Tip: bookmark it so it's one click each evening.

## How the daily update works

Two layers, so it can never break:

1. **Browser-side (always on).** `index.html` embeds the full schedule and
   spoiler-free notes and picks tonight's stage itself using the NZ clock. Open
   it any evening and the right stage is already front-and-centre.

2. **Daily refresh job.** `tools/update_stage.py` (a) deterministically picks
   tonight's stage from the NZ clock, then (b) if the race is on, runs
   `claude -p` with web search to write a **contextual, rider-aware tactical
   preview**, the **standings** going into tonight's stage, and the
   **abandoned/DNF list** — all into `stage-today.js`, which the page prefers
   when present. If the AI step fails or times out, the page falls back to the
   embedded static notes, so it never breaks. Pass `--no-ai` to skip the AI step.

`tools/publish.sh` wraps that: it runs the updater, then commits and pushes the
refreshed data so a connected host (e.g. Vercel) redeploys automatically.

### The spoiler model (important)

Tonight you watch stage `K`; you have already watched stages up to `K-1`. So the
job may only ever use information current as of the *end of stage K-1*:

- **Standings** shown = classification after stage `K-1` (what riders start
  tonight's stage with) — never after stage `K`.
- **DNF/abandoned** riders shown = those out through stage `K-1` only. A
  deterministic guard also strips any DNF the model attributes to stage `K` or
  later.
- **Tactical preview** of stage `K` is written from that pre-stage picture and
  each rider's real characteristics / GC position — never its result.

Residual risk: the AI does a live web search around 14:00 NZ, by which time
tonight's stage has finished in Europe. The prompt forbids looking it up and the
guard above filters DNFs, but if you ever spot a leaked result, run
`python3 tools/update_stage.py --no-ai` to fall back to the safe static notes.

### Timezones

The spoiler-safe snapshot is anchored to **one** viewing schedule — it's frozen
at the start of the stage being watched *that NZ evening*. That's inherent:
"spoiler-safe" is only definable relative to a single watch schedule, so the
page is best understood as a New Zealand highlights companion. Viewers watching
live in Europe (or on any other schedule) would find the standings and notes a
day out of step with their reality. Anchoring it to a different timezone means a
separate daily job pinned to that zone.

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
| `stage-today.js` | Daily data written by the updater (tonight's stage, standings, DNFs). |
| `tools/update_stage.py` | Daily updater — picks tonight's stage + spoiler-safe AI enrichment. |
| `tools/publish.sh` | Runs the updater, then commits + pushes to trigger a redeploy. |
| `tools/*.plist` | Example macOS launchd job (daily 14:00 NZ). |
| `vercel.json` | Static-hosting config (clean URLs, no-cache on `stage-today.js`). |

## Hosting (on Vercel)

The page is plain static HTML, so any static host works. On Vercel: **Add New →
Project → Import this repo → Deploy** (no build step needed). After that, every
push from the daily job auto-deploys.

## Installing the daily job (macOS launchd)

The example plist assumes the repo lives at `~/tour-de-france-2026`; if yours is
elsewhere, edit the paths inside it first. It runs `tools/publish.sh` daily at
14:00 local time.

```sh
cp ~/tour-de-france-2026/tools/com.tdf2026.daily.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.tdf2026.daily.plist
launchctl kickstart gui/$(id -u)/com.tdf2026.daily   # run once now
```

To stop it: `launchctl bootout gui/$(id -u)/com.tdf2026.daily`

Any scheduler works — a cron job, a CI cron, or an n8n workflow hitting a small
endpoint can all run `tools/publish.sh` on the same daily cadence. The AI step
requires the `claude` CLI on `PATH` (or one of the fallback locations in
`update_stage.py`); without it, the job still runs deterministically.

## Refreshing the roster/route data (rosters change during the Tour)

Edit `tdf_data.json`, then regenerate `data.js` from the repo root:

```sh
python3 -c "import json,io; open('data.js','w').write('window.TDF = '+open('tdf_data.json').read()+';')"
```

## Contributing

Contributions welcome — fixes to rosters/route, design tweaks, or a timezone
variant. Keep the spoiler model intact: nothing that reflects a stage's result
should ever reach the page before that stage's highlights are watched. The data
is public sports information; there are no secrets in this repo.
