"""Blueprint v4 Part 4 regime rules. Pure functions, no I/O. Thresholds are fixed by the Blueprint."""
BULL_BREADTH, BEAR_ENTRY_BREADTH, BEAR_EXIT_BREADTH = 55.0, 40.0, 50.0
UNIVERSE = 500

def breadth_pct(count):
    if not isinstance(count, (int, float)) or not 0 <= count <= UNIVERSE:
        raise ValueError(f"breadth count must be 0-{UNIVERSE}, got {count!r}")
    return count * 100 / UNIVERSE

def slope_pct(dma, dma_1m):
    if not (dma > 0 and dma_1m > 0):
        raise ValueError("200 DMA values must be positive")
    return (dma / dma_1m - 1) * 100

def sma(values, n):
    if len(values) < n:
        raise ValueError(f"need {n} values for SMA, have {len(values)}")
    return sum(values[-n:]) / n

def breadth_count(closes, symbols, window=50):
    """closes: {symbol: [last `window` closes, None where missing]}. Returns (count above SMA, symbols lacking data)."""
    above, missing = 0, []
    for s in symbols:
        c = closes.get(s)
        if c is None or len(c) != window or any(v is None for v in c):
            missing.append(s)
        elif c[-1] > sum(c) / window:
            above += 1
    return above, missing

def evaluate(prev_regime, nifty, dma, dma_1m, count, is_friday):
    b, sl = breadth_pct(count), slope_pct(dma, dma_1m)
    above, rising = nifty > dma, sl > 0
    bull = above and rising and b >= BULL_BREADTH
    entry = is_friday and not above and b < BEAR_ENTRY_BREADTH
    exit_ = is_friday and above and b >= BEAR_EXIT_BREADTH
    if prev_regime == "BEAR":
        regime, event = ("NEUTRAL", "BEAR_EXIT") if exit_ else ("BEAR", "BEAR_ACTIVE")
    elif entry:
        regime, event = "BEAR", "BEAR_ENTRY"
    else:
        regime, event = ("BULL" if bull else "NEUTRAL"), ""
    return dict(regime=regime, event=event, breadth_pct=b, slope_pct=sl, above=above, rising=rising,
                bull=bull, entry=entry, exit=exit_)

def validate_record(r):
    num = lambda v: isinstance(v, (int, float)) and v == v
    if not (num(r["nifty_close"]) and r["nifty_close"] > 0): raise ValueError("Nifty close invalid")
    if not (num(r["dma200"]) and r["dma200"] > 0 and num(r["dma200_1m"]) and r["dma200_1m"] > 0): raise ValueError("200 DMA invalid")
    if not (isinstance(r["breadth_count"], int) and 0 <= r["breadth_count"] <= UNIVERSE): raise ValueError("breadth count out of range")
    if not 0 <= r["breadth_pct"] <= 100: raise ValueError("breadth % out of range")
    if not (num(r["india_vix"]) and 0 < r["india_vix"] < 150): raise ValueError("India VIX invalid")
    for k, v in r["sectors"].items():
        if not (num(v) and abs(v) <= 30): raise ValueError(f"sector {k} value invalid: {v!r}")
    check_consistency(r)

def check_consistency(r):
    """Independent re-check of the stored regime against the written rules."""
    a, rising, b = r["nifty_close"] > r["dma200"], r["dma200_slope_pct"] > 0, r["breadth_pct"]
    fri, prev, reg = r["is_week_end"], r.get("previous_regime"), r["regime"]
    bull = a and rising and b >= 55
    if prev == "BEAR":
        exit_ = fri and a and b >= 50
        ok = (reg == "NEUTRAL") if exit_ else (reg == "BEAR")
    elif fri and not a and b < 40:
        ok = reg == "BEAR"
    else:
        ok = reg == ("BULL" if bull else "NEUTRAL")
    if not ok:
        raise ValueError(f"regime {reg} inconsistent with Blueprint rules for these inputs")
