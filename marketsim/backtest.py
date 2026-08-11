#!/usr/bin/env python3
"""Replay the watchlist strategies over a past regular session, minute by minute.

Uses the exact Engine that runs live - only the clock and the bar feed are swapped -
so a green backtest is real evidence the live path works.

    python3 backtest.py                  # most recent completed session
    python3 backtest.py --date 2026-08-06 --capital 1000
"""
import argparse, datetime as dt, json, os, sys, time, zoneinfo
import concurrent.futures as cf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import yf, engine as E                                     # noqa: E402

ET = zoneinfo.ZoneInfo("America/New_York")


def session_bars(sym, day):
    """Regular-session 1-minute bars for `day` (a date)."""
    start = dt.datetime.combine(day, dt.time(4, 0), ET)
    end = dt.datetime.combine(day, dt.time(20, 0), ET)
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={int(start.timestamp())}&period2={int(end.timestamp())}"
           f"&interval=1m&includePrePost=false")
    j = json.loads(yf._get(url))
    res = j["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    bars = []
    for i, t in enumerate(res.get("timestamp", [])):
        o, h, l, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
        if None in (o, h, l, c):
            continue
        et = dt.datetime.fromtimestamp(t, ET)
        if et.date() != day or not (E.OPEN_T <= et.time() < E.CLOSE_T):
            continue
        bars.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": v or 0})
    return bars, res["meta"].get("chartPreviousClose")


def last_session():
    day = E.now_et().date()
    if E.now_et().time() < E.CLOSE_T:
        day -= dt.timedelta(days=1)
    while day.weekday() >= 5 or day.isoformat() in E.HOLIDAYS_2026:
        day -= dt.timedelta(days=1)
    return day


def run(date, capital, wl=None, quiet=False):
    """Replay one session through the live Engine. Returns the finished Engine."""
    wl = wl or json.load(open(os.path.join(HERE, "watchlist.json")))
    syms = [i["sym"] for i in wl["items"]]
    day = dt.date.fromisoformat(date) if isinstance(date, str) else date

    def say(m):
        if not quiet:
            print(m)

    say(f"Replaying {day} with ${capital:,.0f} over {len(syms)} names...")

    def pull(s):
        try:
            return (s, *session_bars(s, day))
        except Exception as ex:
            return s, None, repr(ex)

    feed, prev = {}, {}
    bench, bench_prev = [], None
    with cf.ThreadPoolExecutor(4) as ex:
        for s, bars, pc in ex.map(pull, syms + [E.BENCHMARK]):
            if not bars:
                say(f"  ! no data for {s} ({pc})")
            elif s == E.BENCHMARK:
                bench, bench_prev = bars, pc
            else:
                feed[s], prev[s] = bars, pc

    if not feed:
        raise SystemExit(f"no intraday data available for {day}")
    n = max(len(b) for b in feed.values())
    say(f"  loaded {len(feed)}/{len(syms)} symbols, {n} minutes\n")

    open_dt = dt.datetime.combine(day, E.OPEN_T, ET)
    clock = {"t": open_dt}
    eng = E.Engine(wl, now_fn=lambda: clock["t"])
    eng.reset(capital)
    eng.status = "running"
    for s, pc in prev.items():
        if pc:
            eng.cfg[s]["prevClose"] = pc

    bench_ts = [b["t"] for b in bench]
    for m in range(1, n + 1):
        clock["t"] = open_dt + dt.timedelta(minutes=m)
        cutoff = int(clock["t"].timestamp())
        for s, bars in feed.items():
            sl = bars[:m]
            if sl:
                eng.bars[s] = sl
                eng.last_px[s] = sl[-1]["c"]
        # advance the benchmark by wall clock, not by index - it has its own bar count
        k = sum(1 for t in bench_ts if t <= cutoff)
        eng.bench = bench[:k]
        eng.bench_prev = bench_prev
        eng._manage(m)
        eng._scan(m)
        eng._record()
    eng._flatten("session close")
    eng._record()
    eng.status = "done"
    eng.say(f"Replay of {day} complete.", "good")
    return eng


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default: most recent completed session)")
    ap.add_argument("--capital", type=float, default=1000)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    day = dt.date.fromisoformat(a.date) if a.date else last_session()
    eng = run(day, a.capital)
    snap = eng.snapshot()
    print(f"{'=' * 78}\nRESULT {day}   ${a.capital:,.2f} -> ${snap['equity']:,.2f}"
          f"   P/L ${snap['pl']:+,.2f} ({snap['plPct']:+.2f}%)")
    print(f"{'S&P 500 (open to 15:55)':<26}{snap['benchPct']:+.2f}%"
          f"   -> alpha {snap['alpha']:+.2f} pp")
    print(f"trades {snap['tradeCount']}   win rate {snap['winRate']:.0f}%   "
          f"peak ${max(p['eq'] for p in snap['curve']):,.2f}   "
          f"trough ${min(p['eq'] for p in snap['curve']):,.2f}")
    if snap["haltedReason"]:
        print(f"HALTED: {snap['haltedReason']}")
    print("=" * 78)

    if snap["trades"]:
        print(f"\n{'sym':6}{'side':7}{'strategy':18}{'entry':>9}{'exit':>9}{'P/L':>10}{'%':>8}  held / why")
        for t in sorted(eng.trades, key=lambda x: -x["pl"]):
            print(f"{t['sym']:6}{t['side']:7}{t['strategy']:18}{t['entry']:>9.2f}{t['exit']:>9.2f}"
                  f"{t['pl']:>+10.2f}{t['plPct']:>+8.2f}  {t['opened']}-{t['closed']} {t['why']}")

        by = {}
        for t in eng.trades:
            b = by.setdefault(t["strategy"], [0, 0.0])
            b[0] += 1; b[1] += t["pl"]
        print(f"\n{'strategy':20}{'n':>4}{'P/L':>12}")
        for k, (c, pl) in sorted(by.items(), key=lambda kv: -kv[1][1]):
            print(f"{k:20}{c:>4}{pl:>+12.2f}")

    if a.verbose:
        print("\nlog:")
        for l in reversed(eng.log):
            print(f"  {l['t']}  {l['msg']}")


if __name__ == "__main__":
    main()
