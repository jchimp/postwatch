# Task: Refactor Charts to Use Live Agent Buckets

## Background

The dashboard's hourly and daily charts currently query SQLite and aggregate
delta snapshots grouped by **snapshot timestamp** (when the poller ran), not
by **when the email actually went through Postfix**.
Result: charts show misleading spikes. The first snapshot after a poller
restart, log rotation, or fresh deploy contains a large delta representing
everything since the agent's log started — and that whole batch lands in a
single hour bucket (usually midnight UTC or whenever the poller first ran).
The user has observed an artificial spike at midnight and wants accurate
hour-by-hour mail volume so they can identify real send spikes and dead hours
where the server should have been processing mail but wasn't.

## Goal

Hourly chart shows mail volume **per actual hour the email was processed**,
sourced from log entry timestamps. Daily chart same. Empty hours show as
zero (visible empty bars), not missing entries.

## Approach

- The agent's `/stats` endpoint **already** parses `mail.log` correctly,
  using syslog timestamps to build hourly and daily buckets.
- Refactor the frontend to render those buckets directly via
  `/api/stats/{agent}`. No SQLite aggregation for chart data.
- SQLite is still used for: agent status table (last poll time), token
  history, queue depth history, status active/inactive — these are all
  point-in-time values that ARE correctly bucketed by snapshot timestamp.

  ## In Scope

- Refactor the chart-fetch code in `dashboard/templates/overview.html`
  (`{% block scripts %}`): switch the daily/hourly chart fetches from
  `/api/chart/daily/...` and `/api/chart/hourly/...` (SQLite) to consume
  `hourly` and `daily` objects from `/api/stats/{agent}` (live agent data).
- Decide and act on cleanup:
  - The proxy routes `/api/chart/daily/<agent>` and
    `/api/chart/hourly/<agent>` in `dashboard/app.py`
  - The helpers `get_daily_stats` and `get_hourly_stats` in
    `dashboard/models.py`
  - The delta-tracking columns `sent`, `deferred`, `bounced`, `rejected`,
    `raw_sent`, `raw_deferred`, `raw_bounced`, `raw_rejected` in
    `stats_snapshots` — if charts no longer use deltas, are they still
    needed for anything? Confirm before deleting.
- Surface a small UI note that chart history is limited to what is currently
  in the agent's `mail.log` (rotated logs are not visible). Suggested
  placement: a muted hint in the chart card header.
- Update `CLAUDE.md` to reflect the new data flow.

  ## Out of Scope

- **Do not change the agent.** Its `/stats` endpoint already returns the
  needed `hourly` and `daily` buckets.
- Do not change the Agent Status Table on overview (it is correct).
- Do not change tokens, queue, or any other point-in-time tracking.
- Do not introduce new dependencies.

  ## Constraints

- The dashboard chart is now bounded by what the agent can see in its log
  (currently last 10,000 lines per `/stats` call). That is an acceptable
  trade-off for accuracy.
- Each agent has its own buckets — the agent selector dropdown must
  continue to drive which buckets are shown.
- The Nord/Slate dark theme and stacked bar chart style stay the same.

  ## Code Drift Note

  Code may have drifted from the spec docs (CLAUDE.md, README.md). Inspect
  the actual current state of the repo before making a plan. Specifically:

1. Read `agent/agent.py` and confirm the exact shape of the `/stats`
  JSON response (keys: `totals`, `hourly`, `daily`, etc.) and confirm
  the bucket key format (`YYYY-MM-DD HH` for hourly, `YYYY-MM-DD` for
  daily, last verified).
2. Read `dashboard/models.py` — the schema may have recently been updated
  to include `raw_*` columns for delta tracking. Confirm.
3. Read the current `{% block scripts %}` in
  `dashboard/templates/overview.html` to find the existing chart fetches.
4. Read `dashboard/app.py` to find the current `/api/chart/...` routes.

  ## Deliverables

5. **Plan first.** Summarize: what files change, what code is removed,
  any schema changes, and the new data flow in one short paragraph or
  bullet list. **Confirm the plan with the user before editing files.**
6. After confirmation, deliver complete updated files (do not provide
  diffs unless asked). Likely files: `overview.html` (definitely),
  `app.py` (route cleanup), `models.py` (helper + possibly schema
  cleanup), `CLAUDE.md` (docs).
7. A short summary of what was removed/changed and why.
8. If the SQLite schema changes, include a one-line instruction for
  blowing away the existing DB (the user is okay starting fresh).

  ## Test Plan


- Run `debug_mailstats.py /var/log/mail.log` on a mail server.
- Compare its hourly output to the dashboard's hourly chart for the same
  agent — values must match.
- Confirm the artificial midnight spike is gone.
- Confirm dead hours render as empty bars (height 0), not missing entries
  in the X-axis.
- Confirm switching agents in the dropdown swaps the chart correctly.
- Confirm the Agent Status Table still works (it should be untouched).

  ## Notes

- The user is running this with one or two agents. Performance is not
  a concern at this scale.
- The user prefers minimal dependencies and no build steps. Stick to
  vanilla JS, Jinja2, Bootstrap 5 via CDN, Chart.js via CDN. No npm,
  no transpilers.
- Be direct. No fluff. Confirm before deleting code.
