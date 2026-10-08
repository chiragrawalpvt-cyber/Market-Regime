"""Plumbing tests with SYNTHETIC files (test-only; production never uses generated data)."""
import json, tempfile, unittest
from datetime import date
from pathlib import Path
from regime import update as u

SYMS = [f"SYM{i}" for i in range(500)]
HOL = {date(2026, 10, 2)}

def fake_fetch(url):
    if "ind_nifty500list" in url: return "Company Name,Industry,Symbol,Series,ISIN Code\n" + "\n".join(f"C{s},X,{s},EQ,I" for s in SYMS)
    ds = url.rsplit("_", 1)[1][:8]; d = date(int(ds[4:]), int(ds[2:4]), int(ds[:2]))
    if d in HOL or d.weekday() >= 5: return None
    k = d.toordinal()
    if "ind_close_all" in url:
        rows = [("Nifty 50", 20000 + k * 2), ("India VIX", 14.2)] + [(n, 1000 + k) for n in u.SECTORS]
        return "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value\n" + "\n".join(f'{n.title()},x,0,0,0,{v}' for n, v in rows)
    return "SYMBOL, SERIES, DATE1, CLOSE_PRICE\n" + "\n".join(f"{s}, EQ, x, {100 + k * 0.5}" for s in SYMS)

class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); u.DATA = Path(self.tmp.name); u.SLEEP = 0
        (u.DATA / "records.json").write_text("[]"); u.fetch = fake_fetch
    def tearDown(self): self.tmp.cleanup()
    def rec(self): return json.loads((u.DATA / "records.json").read_text())
    def status(self): return json.loads((u.DATA / "status.json").read_text())

    def test_success_bull_and_idempotent(self):
        self.assertEqual(u.main(["--date", "2026-10-07"]), 0)
        r = self.rec()[0]; self.assertEqual((r["regime"], r["breadth_count"], r["breadth_pct"]), ("BULL", 500, 100.0))
        self.assertEqual(len(r["sectors"]), 15); self.assertEqual(u.main(["--date", "2026-10-07"]), 0); self.assertEqual(len(self.rec()), 1)

    def test_holiday_creates_no_record(self):
        self.assertEqual(u.main(["--date", "2026-10-02"]), 0)
        self.assertEqual((self.rec(), self.status()["state"]), ([], "no_data"))

    def test_weekend_skipped(self):
        self.assertEqual(u.main(["--date", "2026-10-03"]), 0); self.assertEqual(self.rec(), [])

    def test_failure_keeps_previous_record(self):
        u.main(["--date", "2026-10-07"]); before = (u.DATA / "records.json").read_text()
        def boom(url): raise RuntimeError("HTTP 403")
        u.fetch = boom
        self.assertEqual(u.main(["--date", "2026-10-08"]), 1)
        self.assertEqual((u.DATA / "records.json").read_text(), before); self.assertEqual(self.status()["state"], "failed")

if __name__ == "__main__": unittest.main()
