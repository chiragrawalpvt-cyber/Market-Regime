"""Daily regime job: fetch NSE end-of-day files, compute metrics, store one validated record.
I/O only; rules live in engine.py. Never writes records.json unless every validation passes."""
import csv, io, json, os, sys, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import requests
from . import engine

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept": "text/csv,*/*"}
BASE = "https://nsearchives.nseindia.com"
URL_INDEX = BASE + "/content/indices/ind_close_all_{:%d%m%Y}.csv"
URL_BHAV = BASE + "/products/content/sec_bhavdata_full_{:%d%m%Y}.csv"
URL_LIST = BASE + "/content/indices/ind_nifty500list.csv"
SECTORS = {"nifty bank": "Bank", "nifty financial services": "Fin Services", "nifty it": "IT", "nifty auto": "Auto",
           "nifty fmcg": "FMCG", "nifty pharma": "Pharma", "nifty metal": "Metal", "nifty realty": "Realty",
           "nifty energy": "Energy", "nifty oil & gas": "Oil & Gas", "nifty media": "Media", "nifty psu bank": "PSU Bank",
           "nifty consumer durables": "Cons Durables", "nifty healthcare index": "Healthcare", "nifty infrastructure": "Infra"}
NEEDED = {"nifty 50", "india vix", *SECTORS}
IDX_LOOKBACK, STK_LOOKBACK, SLEEP = 400, 90, 0.4

class NoData(Exception):
    pass

def fetch(url):
    last = None
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=30)
        except requests.RequestException as e:
            last = e; time.sleep(2 * (i + 1)); continue
        if r.status_code == 404: return None
        if r.status_code == 200: return r.text
        last = RuntimeError(f"HTTP {r.status_code} for {url}")
        if r.status_code < 500: break
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed: {last}")

def _norm_rows(text):
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        yield {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}

def parse_index(text):
    out = {}
    for row in _norm_rows(text):
        name = row.get("index name", "").lower()
        col = next((k for k in row if k.startswith("closing")), None)
        if name in NEEDED and col:
            try: out[name] = float(row[col].replace(",", ""))
            except ValueError: pass
    if "nifty 50" not in out: raise RuntimeError('index file parsed but "Nifty 50" row missing (format changed?)')
    return out

def parse_bhav(text, symbols):
    out = {}
    for row in _norm_rows(text):
        if row.get("series") == "EQ" and row.get("symbol") in symbols:
            try: out[row["symbol"]] = float(row["close_price"])
            except (KeyError, ValueError): pass
    if not out: raise RuntimeError("bhavcopy parsed but no Nifty 500 EQ rows found (format changed?)")
    return out

def load_symbols():
    cache = DATA / "nifty500.csv"
    try:
        text = fetch(URL_LIST)
        if text is None: raise RuntimeError("constituent list returned 404")
        cache.write_text(text)
    except RuntimeError:
        if not cache.exists(): raise
        text = cache.read_text()
    syms = {r["symbol"] for r in _norm_rows(text) if r.get("symbol")}
    if len(syms) != engine.UNIVERSE: raise RuntimeError(f"Nifty 500 list has {len(syms)} symbols, expected 500")
    return syms

def load_hist(path):
    h = {}
    if path.exists():
        with path.open() as f:
            for r in csv.DictReader(f): h.setdefault(r["date"], {})[r["key"]] = float(r["close"])
    return h

def save_hist(path, h, keep_from):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "key", "close"])
        for d in sorted(h):
            if d >= keep_from:
                for k, v in sorted(h[d].items()): w.writerow([d, k, v])
    os.replace(tmp, path)

def weekdays(a, b):
    d = a
    while d <= b:
        if d.weekday() < 5: yield d
        d += timedelta(1)

def ensure(target, lookback, url, parse, hist, nodata):
    for d in weekdays(target - timedelta(lookback), target):
        ds = d.isoformat()
        if ds in hist or (ds in nodata and d < target): continue
        text = fetch(url.format(d)); time.sleep(SLEEP)
        if text is None:
            if d < target: nodata.add(ds)
            continue
        hist[ds] = parse(text)

def read_json(p, default):
    try: return json.loads(p.read_text())
    except (OSError, ValueError): return default

def write_json(p, obj):
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(obj, indent=1)); os.replace(tmp, p)

def build_record(target, idx, stk, symbols, records):
    ds = target.isoformat()
    if ds not in idx or ds not in stk: raise NoData(f"No NSE files for {ds} yet (holiday or not published).")
    dates = sorted(d for d in idx if d <= ds and "nifty 50" in idx[d])
    closes = [idx[d]["nifty 50"] for d in dates]
    if len(closes) < 200: raise RuntimeError(f"Only {len(closes)} Nifty closes; 200 needed")
    cut = (target - timedelta(30)).isoformat()
    older = [idx[d]["nifty 50"] for d in dates if d <= cut]
    if len(older) < 200: raise RuntimeError(f"Only {len(older)} Nifty closes up to {cut}; 200 needed for 1-month-ago DMA")
    dma, dma1 = engine.sma(closes, 200), engine.sma(older, 200)
    if "india vix" not in idx[ds]: raise RuntimeError("India VIX missing in index file")
    warns, sectors = [], {}
    prev_ds = dates[-2] if len(dates) > 1 else None
    for key, name in SECTORS.items():
        c, p = idx[ds].get(key), idx.get(prev_ds, {}).get(key)
        if c and p: sectors[name] = round((c / p - 1) * 100, 2)
        else: warns.append(f"sector {name} unavailable")
    sess = sorted(d for d in stk if d <= ds)[-50:]
    if len(sess) < 50 or sess[-1] != ds: raise RuntimeError(f"Need 50 stock sessions ending {ds}, have {len(sess)}")
    cby = {s: [stk[d].get(s) for d in sess] for s in symbols}
    count, missing = engine.breadth_count(cby, symbols, 50)
    if len(missing) > 25: raise RuntimeError(f"{len(missing)} constituents lack 50 sessions of data (>25)")
    if missing: warns.append(f"{len(missing)} constituents lacked data and were not counted above SMA50: {', '.join(sorted(missing)[:10])}")
    prev = records[-1] if records else None
    ev = engine.evaluate(prev["regime"] if prev else None, closes[-1], dma, dma1, count, target.weekday() == 4)
    exit_date = ds if ev["event"] == "BEAR_EXIT" else (None if ev["regime"] == "BEAR" else (prev or {}).get("bear_exit_date"))
    rec = dict(date=ds, nifty_close=closes[-1], dma200=round(dma, 2), dma200_1m=round(dma1, 2),
               dma200_slope_pct=round(ev["slope_pct"], 4), breadth_count=count, breadth_pct=round(ev["breadth_pct"], 2),
               india_vix=idx[ds]["india vix"], sectors=sectors, regime=ev["regime"], previous_regime=prev["regime"] if prev else None,
               event=ev["event"], bear_status="ACTIVE" if ev["regime"] == "BEAR" else ("EXITED_TODAY" if ev["event"] == "BEAR_EXIT" else "NONE"),
               is_week_end=target.weekday() == 4, bear_exit_date=exit_date,
               post_bear_trades_allowed=3 if exit_date else 0,
               warnings=warns, source="NSE archives (ind_close_all, sec_bhavdata_full, ind_nifty500list)",
               generated_at_ist=datetime.now(IST).isoformat(timespec="seconds"))
    engine.validate_record(rec)
    return rec

def run(target):
    records = read_json(DATA / "records.json", [])
    ds = target.isoformat()
    if records and records[-1]["date"] >= ds:
        return "ok", f"{ds} already recorded" if records[-1]["date"] == ds else f"latest record {records[-1]['date']} is newer than {ds}"
    symbols = load_symbols()
    hdir = DATA / "history"; hdir.mkdir(parents=True, exist_ok=True)
    nod = read_json(hdir / "nodata.json", {"index": [], "bhav": []})
    ni, nb = set(nod["index"]), set(nod["bhav"])
    idx = load_hist(hdir / "index.csv")
    stk = load_hist(hdir / "stocks.csv")
    ensure(target, IDX_LOOKBACK, URL_INDEX, parse_index, idx, ni)
    ensure(target, STK_LOOKBACK, URL_BHAV, lambda t: parse_bhav(t, symbols), stk, nb)
    save_hist(hdir / "index.csv", idx, (target - timedelta(IDX_LOOKBACK)).isoformat())
    save_hist(hdir / "stocks.csv", stk, (target - timedelta(STK_LOOKBACK)).isoformat())
    write_json(hdir / "nodata.json", {"index": sorted(ni), "bhav": sorted(nb)})
    rec = build_record(target, idx, stk, symbols, records)
    write_json(DATA / "records.json", records + [rec])
    return "ok", f"recorded {ds}: {rec['regime']}"

def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    target = date.fromisoformat(argv[argv.index("--date") + 1]) if "--date" in argv else datetime.now(IST).date()
    if target.weekday() >= 5:
        print(f"{target} is a weekend: nothing to do"); return 0
    try: state, msg = run(target)
    except NoData as e: state, msg = "no_data", str(e)
    except Exception as e: state, msg = "failed", f"{type(e).__name__}: {e}"
    recs = read_json(DATA / "records.json", [])
    write_json(DATA / "status.json", dict(state=state, message=msg, target_date=target.isoformat(),
               last_run_ist=datetime.now(IST).isoformat(timespec="seconds"), last_record_date=recs[-1]["date"] if recs else None))
    print(state, msg)
    return 1 if state == "failed" else 0

if __name__ == "__main__":
    sys.exit(main())
