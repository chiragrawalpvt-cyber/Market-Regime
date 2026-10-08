import unittest
from regime import engine as e

def ev(prev, n, m, m1, c, fri): return e.evaluate(prev, n, m, m1, c, fri)

class Scenarios(unittest.TestCase):
    def test_A_bull(self): self.assertEqual(ev(None, 25000, 24000, 23500, 300, False)["regime"], "BULL")
    def test_B_neutral(self): self.assertEqual(ev(None, 23500, 24000, 23500, 250, False)["regime"], "NEUTRAL")
    def test_C_bear_entry(self):
        r = ev(None, 23500, 24000, 23500, 175, True); self.assertEqual((r["regime"], r["event"]), ("BEAR", "BEAR_ENTRY"))
    def test_C2_below_but_not_friday(self): self.assertEqual(ev(None, 23500, 24000, 23500, 175, False)["regime"], "NEUTRAL")
    def test_D_sticky(self):
        r = ev("BEAR", 24500, 24000, 23500, 275, False); self.assertEqual((r["regime"], r["event"]), ("BEAR", "BEAR_ACTIVE"))
    def test_E_exit(self):
        r = ev("BEAR", 24500, 24000, 23500, 250, True); self.assertEqual((r["regime"], r["event"]), ("NEUTRAL", "BEAR_EXIT"))
    def test_E2_exit_needs_50(self): self.assertEqual(ev("BEAR", 24500, 24000, 23500, 249, True)["regime"], "BEAR")
    def test_F_breadth(self): self.assertEqual(e.breadth_pct(275), 55.0)
    def test_bull_needs_rising(self): self.assertEqual(ev(None, 25000, 24000, 24000, 300, False)["regime"], "NEUTRAL")
    def test_breadth_range(self):
        for bad in (-1, 501): self.assertRaises(ValueError, e.breadth_pct, bad)
    def test_slope(self): self.assertAlmostEqual(e.slope_pct(24000, 23500), 2.1277, 3)

class Calc(unittest.TestCase):
    def test_sma(self): self.assertEqual(e.sma([1, 2, 3, 4], 2), 3.5); self.assertRaises(ValueError, e.sma, [1], 2)
    def test_breadth_count(self):
        up = list(range(1, 51)); dn = list(range(50, 0, -1)); gap = up[:-1] + [None]
        a, miss = e.breadth_count({"U": up, "D": dn, "G": gap}, ["U", "D", "G", "X"], 50)
        self.assertEqual((a, sorted(miss)), (1, ["G", "X"]))
    def test_consistency_rejects_wrong_regime(self):
        r = dict(nifty_close=25000, dma200=24000, dma200_slope_pct=2.0, breadth_pct=60, is_week_end=False, previous_regime=None, regime="NEUTRAL")
        self.assertRaises(ValueError, e.check_consistency, r)

if __name__ == "__main__": unittest.main()
