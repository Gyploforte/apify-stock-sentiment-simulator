#!/usr/bin/env python3
"""Trade-level diagnostics for replayed marketsim sessions.

Separates structural defects (actionable from one session) from performance claims
(which need sample size). Reports mean and median side by side everywhere, because
small books are dominated by outliers.

    python3 diagnose.py <marketsim-dir> 2026-08-07
    python3 diagnose.py <marketsim-dir> 2026-08-04 2026-08-05 2026-08-06 2026-08-07
"""
import sys, os, datetime as dt, statistics, collections, zoneinfo

if len(sys.argv) < 3:
    sys.exit(__doc__)

MSDIR = os.path.abspath(sys.argv[1])
DATES = sys.argv[2:]
sys.path.insert(0, MSDIR)

import backtest, engine as E  # noqa: E402

ET = zoneinfo.ZoneInfo("America/New_York")


def mins_of(ts):
    d = dt.datetime.fromtimestamp(ts, ET)
    return d.hour * 60 + d.minute


def hhmm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def stat(vals):
    if not vals:
        return "n/a"
    m, md = statistics.mean(vals), statistics.median(vals)
    flag = "  <-- MEAN AND MEDIAN DISAGREE IN SIGN" if m * md < 0 else ""
    return f"mean {m:+.2f}%  median {md:+.2f}%{flag}"


pooled = []
print(f"Diagnosing {len(DATES)} session(s) from {MSDIR}\n")

for date in DATES:
    day = dt.date.fromisoformat(date)
    eng = backtest.run(day, 1000.0, quiet=True)
    ret = (eng.mark() / 1000 - 1) * 100
    bench = eng.bench_pct()

    print("=" * 78)
    print(f"{date}   {ret:+.2f}%   benchmark {bench:+.2f}%   "
          f"alpha {ret - bench:+.2f} pp   {len(eng.trades)} trades")
    print("=" * 78)

    if not eng.trades:
        print("  no trades\n")
        continue

    # --- exit-reason census: catches dead parameters -----------------------------
    census = collections.Counter(t["why"] for t in eng.trades)
    print("\nexit reasons:")
    for k, n in census.most_common():
        print(f"  {k:<24}{n:>3}   {n / len(eng.trades) * 100:>5.1f}%")
    for dead in ("target hit", "stop hit"):
        if census.get(dead, 0) == 0:
            print(f"  !! '{dead}' NEVER FIRED - structural, check the parameter")

    # --- excursions ---------------------------------------------------------------
    rows = []
    for t in eng.trades:
        try:
            bars, _ = backtest.session_bars(t["sym"], day)
        except Exception:
            continue
        o, c = hhmm(t["opened"]), hhmm(t["closed"])
        held = [b for b in bars if o <= mins_of(b["t"]) <= c]
        if not held:
            continue
        e, long = t["entry"], t["side"] == "long"
        mfe = (max(b["h"] for b in held) - e) if long else (e - min(b["l"] for b in held))
        mae = (e - min(b["l"] for b in held)) if long else (max(b["h"] for b in held) - e)
        rows.append((t, mfe / e * 100, mae / e * 100))
        pooled.append((date, t, mfe / e * 100, mae / e * 100, bench))

    if rows:
        mfes = [r[1] for r in rows]
        maes = [-r[2] for r in rows]
        print(f"\nfavourable excursion  {stat(mfes)}")
        print(f"adverse excursion     {stat(maes)}")
        if statistics.median(mfes) < -statistics.median(maes):
            print("  !! trades went further against than for - entry timing, not stop width")

        never = [r for r in rows if r[1] < 0.25]
        if never:
            print(f"\ntrades that never worked at all (best excursion < +0.25%): {len(never)}")
            for t, mfe, mae in never:
                print(f"  {t['sym']:6} P/L {t['pl']:+7.2f}   best {mfe:+.2f}%   {t['why']}")

    # --- returns, mean vs median --------------------------------------------------
    print(f"\nall trades      {stat([t['plPct'] for t in eng.trades])}")
    for side in ("long", "short"):
        g = [t["plPct"] for t in eng.trades if t["side"] == side]
        if g:
            print(f"{side:<16}{stat(g)}   n={len(g)}")
            top = max((t for t in eng.trades if t["side"] == side), key=lambda x: abs(x["plPct"]))
            if len(g) > 2 and abs(top["plPct"]) > 3 * statistics.median([abs(x) for x in g]):
                print(f"  -> dominated by one outlier: {top['sym']} {top['plPct']:+.2f}%")

    # --- concentration ------------------------------------------------------------
    by = collections.defaultdict(list)
    for t in eng.trades:
        by[t["bucket"]].append(t)
    multi = {k: v for k, v in by.items() if len(v) > 1 and len({t["side"] for t in v}) == 1}
    if multi:
        print("\nbuckets traded in one direction only (correlated, not independent bets):")
        for k, v in multi.items():
            print(f"  {k:<24}n={len(v)}  P/L {sum(t['pl'] for t in v):+7.2f}")

    gl = sum(t["qty"] * t["entry"] for t in eng.trades if t["side"] == "long")
    gs = sum(t["qty"] * t["entry"] for t in eng.trades if t["side"] == "short")
    print(f"\ncumulative gross long ${gl:,.0f} / short ${gs:,.0f} -> net ${gl - gs:+,.0f}")
    print()

# --- pooled ---------------------------------------------------------------------
if len(DATES) > 1 and pooled:
    print("=" * 78)
    print(f"POOLED — {len(pooled)} trades over {len(DATES)} sessions")
    print("=" * 78)
    print(f"favourable excursion  {stat([p[2] for p in pooled])}")
    print(f"adverse excursion     {stat([-p[3] for p in pooled])}")
    print(f"trade return          {stat([p[1]['plPct'] for p in pooled])}")
    census = collections.Counter(p[1]['why'] for p in pooled)
    print("\npooled exit reasons:")
    for k, n in census.most_common():
        print(f"  {k:<24}{n:>3}   {n / len(pooled) * 100:>5.1f}%")

    print(f"\nsample size: {len(pooled)} trades.", end=" ")
    if len(pooled) < 50:
        print("Too few for parameter tuning. Structural defects only —\n"
              "  a parameter that never binds is actionable; 'this rule lost money' is not.")
    elif len(pooled) < 200:
        print("Enough for gross structural defects, not for comparing rules.")
    else:
        print("Enough to assess the book against its benchmark.")
    print("\nReminder: sessions at or before the watchlist's build date are in-sample.\n"
          "Report those separately — they are not evidence.")
