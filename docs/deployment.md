# Deployment & the daily trigger

This project is **seasonal** — it only needs to update while the Tour is running
(≈3 weeks each July). The daily refresh is driven by the **canonical Growth Medium
Ops webhook listener**, not by anything in this repo. This doc is the enable/disable
runbook so it's trivial to switch on when the Tour opens and off when it ends.

## The trigger chain

```
n8n Schedule (10:00 NZ, Pacific/Auckland)
  → HTTP POST  /trigger   { "type": "tdf_daily" }   (header X-Webhook-Secret)
    → growth-medium-ops/tools/webhook_listener.py   (port 8765, Cloudflare-tunnelled)
      → fire_script(~/tour-de-france-2026/tools/publish.sh, "tdf_daily")
        → update_stage.py   (Exa/Firecrawl fetch → fast claude extraction → stage-today.js)
        → git commit + push
          → Vercel auto-deploys
```

Nothing here needs its own listener, tunnel, secret, or launchd job — it reuses the
same `/trigger` plumbing as every other n8n cron (`daily_briefing`, `daily_workout`, …).

## 10:00 is load-bearing

The site flips from "Start of Stage X" to "End of Stage X" at **`BOUNDARY_HOUR`** in
[`tools/update_stage.py`](../tools/update_stage.py). The browser reads that hour from
the payload, so **the code has one source of truth** — but the **n8n cron hour must
match it**. To move the flip, change *both* `BOUNDARY_HOUR` and the cron. The result
of a stage only enters the published file at the flip, so the cron must fire at the
flip hour (not before), or the reveal never lands. Cron timezone **must** be
`Pacific/Auckland` — n8n defaults to UTC, which would fire at 22:00 NZ.

---

## Enable (at the start of the Tour)

1. **Keys** — confirm `tools/.research.env` (gitignored) has:
   ```
   EXA_API_KEY=...
   FIRECRAWL_API_KEY=...
   ```
   (`publish.sh` sources this.) If missing, copy the two lines from
   `~/growth-medium-ops/.env`.

2. **Listener branch** — confirm the `tdf_daily` branch exists in
   `~/growth-medium-ops/tools/webhook_listener.py` (search `tdf_daily`). If you
   removed it after last year, re-add the branch + its docstring line, then restart:
   ```sh
   launchctl kickstart -k gui/$(id -u)/com.growthmedium.webhook-listener
   ```

3. **n8n node** — duplicate any existing `/trigger` schedule workflow and change:
   - **Schedule**: cron `0 0 10 * * *`, timezone **`Pacific/Auckland`**
   - **HTTP Request body**: `{ "type": "tdf_daily" }`
   - (Endpoint + `X-Webhook-Secret` header are already set on the duplicated node.)
   Activate it, and confirm the node's "next execution" shows **10:00 NZST**.

4. **Smoke test** — fire it once by hand without waiting for 10:00:
   ```sh
   curl -X POST https://<tunnel-host>/trigger \
     -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
     -H "Content-Type: application/json" \
     -d '{"type":"tdf_daily"}'
   ```
   Watch the listener log; within ~2–3 min a `chore: daily TdF update` commit should
   land and Vercel redeploy.

## Disable (at the end of the Tour)

1. **n8n** — deactivate (or delete) the `tdf_daily` schedule workflow.
2. **Listener** — remove the `tdf_daily` branch **and** its docstring line from
   `~/growth-medium-ops/tools/webhook_listener.py`, then restart it (kickstart as
   above). Leaving it in is harmless (it just never fires), but removing keeps the
   dispatcher clean.
3. **Keys** — optional: delete `tools/.research.env`. No cost if left (unused).

Re-enabling next July is just the Enable steps again.

---

## Running it manually

From the repo root, any time:

```sh
set -a; . tools/.research.env; set +a          # load Exa/Firecrawl keys
python3 tools/update_stage.py                  # regenerate stage-today.js only
# or the full publish (regenerate + commit + push):
bash tools/publish.sh
```

Useful flags on `update_stage.py`: `--no-ai` (deterministic pick only, skips the
standings fetch — the page then shows a graceful "updating…" for standings),
`--model ''` (use the CLI's default model instead of `sonnet`), `--timeout <s>`.
