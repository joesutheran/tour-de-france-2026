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

2. **Daily refresh job.** `tools/update_stage.py` (a) works out — from the NZ
   clock and the **10:00 boundary** — which stage you've just watched and which
   you'll watch next, then (b) if the race is on, runs `claude -p` with web
   search to write a **contextual, rider-aware tactical preview** of the next
   stage, the **standings at the end of the just-watched stage**, and the
   **abandoned/DNF list** — all into `stage-today.js`, which the page prefers
   when present. If the AI step fails or times out, the page falls back to the
   embedded static notes, so it never breaks. Pass `--no-ai` to skip the AI step.

`tools/publish.sh` wraps that: it runs the updater, then commits and pushes the
refreshed data so a connected host (e.g. Vercel) redeploys automatically.

### The 10:00 flip (the core model)

Everything is keyed to a single pointer that advances each morning at **10:00 NZ**.
Let `X` be the stage you watch this cycle (you watch before the flip):

| Window (NZ) | Hero previews | Standings label | Standings data |
|---|---|---|---|
| 00:00–09:59 | **Stage X** (up next) | **Start of Stage X** | end of Stage X−1 |
| 10:00–23:59 | **Stage X+1** (coming up) | **End of Stage X** | end of Stage X |

Because *End of Stage X ≡ Start of Stage X+1*, one file generated at 10:00 serves
both the post-flip window and the next morning's pre-flip window — the browser
just relabels at the boundary. The whole page rolls forward one stage at 10:00.
(The flip hour is set once by `BOUNDARY_HOUR`; move it and the cron together.)

### The spoiler model (important)

The result of Stage X **only enters the published file at 10:00**, exactly when
you watch it — so there is never an unwatched result in the page source. The job:

- **Standings** = classification after the just-watched stage. Never a stage you
  haven't seen (the browser refuses to show standings tagged to the wrong stage
  boundary, falling back to a neutral "updating…" state).
- **DNF/abandoned** = those out through the just-watched stage only. A
  deterministic guard strips any DNF the model attributes to a later stage.
- **Tactical preview** of the *next* stage is written from the pre-stage picture
  and each rider's real characteristics / GC position — never its result (that
  stage hasn't been raced yet in Europe when the job runs).

If you ever spot a leaked result, run `python3 tools/update_stage.py --no-ai` to
fall back to the safe static notes. `BOUNDARY_HOUR` in `update_stage.py` and the
`boundary_hour` in the payload (read by `index.html`) must stay in sync.

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
| `stage-today.js` | Daily data written by the updater (watched stage, standings, DNFs, next-stage preview). |
| `tools/update_stage.py` | Daily updater — resolves the 10:00 pointer + fetches standings (Exa/Firecrawl → fast extraction). |
| `tools/publish.sh` | Sources `tools/.research.env`, runs the updater, then commits + pushes to trigger a redeploy. |
| `tools/.research.env` | Gitignored — Exa/Firecrawl API keys for the standings fetch. |
| `docs/deployment.md` | Enable/disable runbook for the seasonal daily trigger. |
| `vercel.json` | Static-hosting config (clean URLs, no-cache on `stage-today.js`). |

## Hosting (on Vercel)

The page is plain static HTML, so any static host works. On Vercel: **Add New →
Project → Import this repo → Deploy** (no build step needed). After that, every
push from the daily job auto-deploys.

## Triggering the daily update

The daily 10:00 NZ refresh is driven by the **canonical Growth Medium Ops webhook
listener** (`growth-medium-ops/tools/webhook_listener.py`, `POST /trigger` with
`{ "type": "tdf_daily" }`) — the same tunnelled dispatcher every other n8n cron
uses. This repo stands up **no listener, tunnel, secret, or launchd job** of its
own; it only supplies `publish.sh` (which the listener runs) and its Exa/Firecrawl
keys in `tools/.research.env`.

Because it's seasonal, the full **enable / disable runbook** lives in
[`docs/deployment.md`](docs/deployment.md) — turn it on when the Tour opens
(add the n8n node + confirm the `tdf_daily` listener branch), off when it ends.

`10:00` is load-bearing: `BOUNDARY_HOUR` in `update_stage.py` (the flip hour, which
the browser reads from the payload) and the n8n cron hour must match — change one,
change both. The `claude` CLI must be on `PATH`; without it the job still runs
deterministically (standings show a graceful "updating…").

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
