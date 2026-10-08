# Market Regime: automated daily dashboard (Blueprint v4 Part 4)

Flow: GitHub Actions cron -> `python -m regime.update` -> `data/records.json` + `data/status.json` committed to the repo -> static `index.html` reads them. No browser needs to be open.
Rules live only in `regime/engine.py` (Bull / Bear entry / Bear exit / Neutral, sticky Bear, Friday-only Bear decisions). VIX and sectors are context only.

## Data source (NSE end-of-day archive files, public, no API key)
- `ind_close_all_DDMMYYYY.csv`: Nifty 50, India VIX, sector index closes
- `sec_bhavdata_full_DDMMYYYY.csv`: closes of all stocks (series EQ)
- `ind_nifty500list.csv`: the 500 constituents (cached in data/nifty500.csv; cache used only if the live download fails)
Breadth = Nifty 500 stocks with close > own 50-session SMA / 500 x 100. 200 DMA = mean of last 200 Nifty closes. DMA ~1 month ago = same SMA as of the last session on or before (date - 30 days). Sector % = close vs previous session.

## Limits and failure behaviour
- NSE publishes after the close, often later than 17:00 IST. Runs at 17:00, 18:30, 21:00 IST; the first run that finds files writes the record (idempotent). GitHub cron can start up to ~1 hour late.
- Weekend: skipped. Weekday without files: status `no_data`, no record (holiday or not published yet).
- Any error, 403 block, parse or validation failure: records.json untouched, status.json = `failed` with timestamp, workflow turns red, dashboard shows "Data update failed".
- Missing sector index: saved with a warning. Missing Nifty, VIX, DMA history, or >25 constituents lacking 50 sessions: rejected.
- Closes are unadjusted: a split/bonus inside the 50-session window can distort that stock's SMA50.
- Post-Bear "first 3 trades" counter is manual (button; stored in your browser). The server cannot know your trades.
- First record starts with no previous regime (Neutral/Bull per rules). If the market is already in a Bear phase, Bear is only detected on the first qualifying Friday.
- Friday market holiday: no Bear entry/exit decision that week (Thursday is not treated as week-end).

## Deploy
1. Create a GitHub repo, push all files.
2. Settings -> Actions -> General -> Workflow permissions: Read and write.
3. Actions -> daily-regime -> Run workflow (first run backfills ~400 days of index files and ~90 of stock files; several minutes; later runs are fast).
4. Hosting: GitHub Pages (Settings -> Pages -> Source: GitHub Actions; Settings -> Variables -> `DEPLOY_PAGES` = `true`; free Pages needs a public repo) or Netlify (connect repo, publish dir `/`, no build command).
5. Read the day-one Actions log. If a URL or column differs, the run fails loudly with the reason.

Tests: `python -m unittest discover -s tests` (also run before every job).
