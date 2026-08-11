"""Paper-trading engine: real Yahoo Finance prices, simulated fills, no broker.

The engine owns a single portfolio. It polls 1-minute bars for the whole watchlist
once a minute, builds a `Ctx` per symbol, asks that symbol's strategy for an entry,
and manages exits generically. Nothing here can place a real order - every fill is
written into the in-process portfolio only.
"""
import json, os, threading, time, datetime as dt, zoneinfo
import concurrent.futures as cf

import yf
import strategies as S

ET = zoneinfo.ZoneInfo("America/New_York")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "state.json")

OPEN_T = dt.time(9, 30)
CLOSE_T = dt.time(16, 0)
# 2026 NYSE full-day closures
HOLIDAYS_2026 = {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
                 "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"}

BENCHMARK = "^GSPC"       # S&P 500, tracked but never traded
SLIPPAGE_BPS = 5.0        # each way, on top of the traded price
MAX_POSITIONS = 10
MAX_WEIGHT = 0.18         # of starting equity, per position
MAX_GROSS = 1.5           # total gross notional as a multiple of equity
DAILY_STOP = -0.08        # halt trading for the day at -8%
TRAIL_AFTER_R = 1.0       # start trailing once a trade is +1R
TRAIL_FRAC = 0.5          # trail at 50% of the open profit

# Regime gate. A size haircut rather than a veto: the tape can be wrong too, and a
# hard block would have thrown away DOCS - the best trade of the reference session -
# purely for being short on an up day.
REGIME_GATE = True
REGIME_THRESH = 0.30      # % move in the benchmark, from the open, to call a regime
REGIME_MIN_BARS = 20      # don't judge the day off the first few minutes
REGIME_HAIRCUT = 0.5      # size multiplier for entries fighting the tape
# Setup-driven rules trade a specific dislocation, not a market view, so they are exempt.
REGIME_EXEMPT = {"gap_fade_short", "gap_fade_long", "mean_rev_long"}


def now_et():
    return dt.datetime.now(ET)


def market_phase(t=None):
    """-> ('closed'|'premarket'|'open'|'afterhours', minutes_since_open)"""
    t = t or now_et()
    if t.weekday() >= 5 or t.strftime("%Y-%m-%d") in HOLIDAYS_2026:
        return "closed", 0
    mins = (t.hour * 60 + t.minute) - (OPEN_T.hour * 60 + OPEN_T.minute)
    if t.time() < dt.time(4, 0):
        return "closed", mins
    if t.time() < OPEN_T:
        return "premarket", mins
    if t.time() < CLOSE_T:
        return "open", mins
    if t.time() < dt.time(20, 0):
        return "afterhours", mins
    return "closed", mins


class Engine:
    """`now_fn` is injectable so the same code can be replayed over a past session
    by backtest.py - the live server just uses the wall clock."""

    def __init__(self, watchlist, now_fn=None):
        self.wl = watchlist
        self.syms = [i["sym"] for i in watchlist["items"]]
        self.cfg = {i["sym"]: dict(i) for i in watchlist["items"]}
        self.now = now_fn or now_et
        self.lock = threading.RLock()
        self.thread = None
        self.stop_flag = threading.Event()
        self.bars = {}          # sym -> list of session 1m bars
        self.last_px = {}
        self.bench = []         # benchmark session bars, tracked but never traded
        self.bench_prev = None  # benchmark prior close, for the regime read
        self.reset(0)

    def regime(self):
        """Read the tape's own direction from the benchmark: 'risk_on'|'risk_off'|'neutral'.

        Friday 2026-08-07 is why this exists. The plan was built on a hawkish-Fed thesis
        hours before the open; the 08:30 payroll print inverted it twelve minutes before
        the bell, and the engine executed the short book straight into a rally because
        nothing connected the macro read to the positions. Rather than try to parse the
        news, just ask what the index is actually doing - by the time the opening range
        has formed, the tape has already voted.
        """
        if not REGIME_GATE or len(self.bench) < REGIME_MIN_BARS:
            return "neutral"
        # Measured from the PRIOR CLOSE, deliberately unlike bench_pct(), which starts at
        # the open. Performance and regime are different questions: we do not hold the
        # overnight gap, so it must not flatter our return - but the gap is precisely
        # where an overnight repricing shows up, so it must inform the regime read.
        # On 2026-08-07 the index moved only +0.26% intraday while closing +0.62%; an
        # open-based gate never fired on the very day it was designed for.
        base = self.bench_prev or self.bench[0]["o"]
        px = self.bench[-1]["c"]
        pct = (px / base - 1) * 100
        pv = sum(((b["h"] + b["l"] + b["c"]) / 3) * b["v"] for b in self.bench)
        vol = sum(b["v"] for b in self.bench)
        vwap = pv / vol if vol else px
        if pct > REGIME_THRESH and px > vwap:
            return "risk_on"
        if pct < -REGIME_THRESH and px < vwap:
            return "risk_off"
        return "neutral"

    def bench_pct(self):
        """Benchmark return measured from the opening print, not the prior close.

        The portfolio starts flat at 09:30 and is flat again by 15:55, so it never
        holds the overnight gap - charging it against a close-to-close index number
        would be comparing two different exposures.
        """
        if len(self.bench) < 2:
            return 0.0
        return (self.bench[-1]["c"] / self.bench[0]["o"] - 1) * 100

    # ----------------------------------------------------------------- state
    def reset(self, capital):
        with self.lock:
            self.capital = float(capital)
            self.cash = float(capital)
            self.positions = {}
            self.trades = []
            self.equity = []
            self.log = []
            self.status = "idle"      # idle | armed | running | halted | done
            self.scan_rows = []
            self.halted_reason = None
            self.started_at = None
            self.last_refresh = None
            self.errors = 0

    def say(self, msg, kind="info"):
        with self.lock:
            self.log.insert(0, {"t": self.now().strftime("%H:%M:%S"), "msg": msg, "kind": kind})
            del self.log[400:]

    def mark(self):
        """Mark-to-market equity: cash + long market value - short market value.

        Short proceeds are credited to cash at open, so the short leg must be
        subtracted here or the position would be counted twice.
        """
        eq = self.cash
        for sym, p in self.positions.items():
            px = self.last_px.get(sym, p["entry"])
            eq += p["qty"] * px if p["side"] == "long" else -p["qty"] * px
        return eq

    def gross(self):
        """Gross notional exposure across both sides."""
        return sum(p["qty"] * self.last_px.get(s, p["entry"]) for s, p in self.positions.items())

    def snapshot(self):
        with self.lock:
            eq = self.mark()
            pos = []
            for sym, p in self.positions.items():
                px = self.last_px.get(sym, p["entry"])
                pl = (px - p["entry"]) * p["qty"] * (1 if p["side"] == "long" else -1)
                pos.append({**p, "sym": sym, "price": px, "pl": pl,
                            "plPct": pl / (p["entry"] * p["qty"]) * 100 if p["qty"] else 0})
            wins = [t for t in self.trades if t["pl"] > 0]
            return {
                "status": self.status,
                "haltedReason": self.halted_reason,
                "phase": market_phase(self.now())[0],
                "etTime": self.now().strftime("%Y-%m-%d %H:%M:%S"),
                "minsOpen": market_phase(self.now())[1],
                "capital": self.capital,
                "cash": self.cash,
                "equity": eq,
                "pl": eq - self.capital,
                "plPct": (eq / self.capital - 1) * 100 if self.capital else 0,
                "benchName": "S&P 500",
                "benchPct": (bp := self.bench_pct()),
                "alpha": ((eq / self.capital - 1) * 100 - bp) if self.capital else 0,
                "positions": sorted(pos, key=lambda x: -abs(x["pl"])),
                "trades": self.trades[-100:][::-1],
                "tradeCount": len(self.trades),
                "winRate": len(wins) / len(self.trades) * 100 if self.trades else 0,
                "curve": self.equity,
                "scan": self.scan_rows,
                "log": self.log[:120],
                "lastRefresh": self.last_refresh,
                "errors": self.errors,
            }

    # ------------------------------------------------------------- lifecycle
    def start(self, capital):
        with self.lock:
            if self.status in ("running", "armed"):
                return False, "already running"
            self.reset(capital)
            phase = market_phase(self.now())[0]
            self.status = "running" if phase == "open" else "armed"
            self.started_at = self.now().isoformat()
            self.stop_flag.clear()
        if phase == "open":
            self.say(f"Started with ${capital:,.0f}. Market is OPEN - trading {len(self.syms)} names.", "good")
        else:
            self.say(f"Armed with ${capital:,.0f}. Market is {phase.upper()} - "
                     f"trading begins automatically at 09:30 ET.", "warn")
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return True, phase

    def stop(self):
        self.stop_flag.set()
        with self.lock:
            if self.positions:
                for sym in list(self.positions):
                    self._close(sym, self.last_px.get(sym, self.positions[sym]["entry"]), "manual stop")
            self.status = "done"
        self.say("Stopped by user. All positions flattened.", "warn")

    # ------------------------------------------------------------- main loop
    def _loop(self):
        while not self.stop_flag.is_set():
            try:
                phase, mins = market_phase(self.now())
                if self.status == "armed":
                    if phase == "open":
                        self.status = "running"
                        self.say("Opening bell - strategies are live.", "good")
                    else:
                        self._sleep(20)
                        continue

                if self.status == "running":
                    if phase == "open":
                        self._refresh()
                        self._manage(mins)
                        self._scan(mins)
                        self._build_scan(mins)
                        self._record()
                    elif phase in ("afterhours", "closed") and mins >= S.SESSION_MINUTES:
                        self._flatten("session close")
                        self._record()
                        self.status = "done"
                        self.say("Session closed. Final P/L booked.", "good")
                        self._persist()
                        return
                    else:
                        self._sleep(20)
                        continue

                if self.status in ("done", "halted"):
                    self._persist()
                    return

                self._persist()
            except Exception as e:                     # keep the loop alive, surface it
                self.errors += 1
                self.say(f"Engine error: {type(e).__name__}: {e}", "bad")
            self._sleep(30)

    def _sleep(self, secs):
        self.stop_flag.wait(secs)

    # ------------------------------------------------------------------ data
    def _refresh(self):
        """Pull today's 1-minute regular-session bars for the whole watchlist."""
        def one(sym):
            try:
                ch = yf.chart(sym, "1d", "1m", prepost=False)
                meta, ts = ch["meta"], ch["t"]
                bars = []
                for i, t in enumerate(ts):
                    o, h, l, c, v = ch["o"][i], ch["h"][i], ch["l"][i], ch["c"][i], ch["v"][i]
                    if None in (o, h, l, c):
                        continue
                    et = dt.datetime.fromtimestamp(t, ET)
                    if not (OPEN_T <= et.time() < CLOSE_T):
                        continue
                    bars.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": v or 0})
                return sym, bars, meta.get("chartPreviousClose") or meta.get("previousClose")
            except Exception:
                return sym, None, None

        with cf.ThreadPoolExecutor(4) as ex:
            for sym, bars, prev in ex.map(one, self.syms + [BENCHMARK]):
                if not bars:
                    continue
                with self.lock:
                    if sym == BENCHMARK:
                        self.bench = bars
                        self.bench_prev = prev or self.bench_prev
                        continue
                    self.bars[sym] = bars
                    self.last_px[sym] = bars[-1]["c"]
                    if prev:
                        self.cfg[sym]["prevClose"] = prev
        self.last_refresh = self.now().strftime("%H:%M:%S")

    def _ctx(self, sym):
        c = self.cfg[sym]
        return S.Ctx(sym, self.bars.get(sym, []), c.get("prevClose"),
                     c.get("atr14"), c["params"]["or_min"])

    # ----------------------------------------------------------------- fills
    def _fill(self, px, side, opening):
        """Slippage always works against us."""
        adverse = (side == "long") == opening
        return px * (1 + SLIPPAGE_BPS / 1e4) if adverse else px * (1 - SLIPPAGE_BPS / 1e4)

    def _open(self, sym, entry, px):
        with self.lock:
            if sym in self.positions or len(self.positions) >= MAX_POSITIONS:
                return
            cfgp = self.cfg[sym]["params"]
            fill = self._fill(px, entry.side, True)
            risk_per_share = abs(fill - entry.stop)
            if risk_per_share <= 0:
                return
            eq = self.mark()
            risk_frac = cfgp["risk"]
            fights = ((entry.side == "long" and self.regime() == "risk_off")
                      or (entry.side == "short" and self.regime() == "risk_on"))
            if fights and self.cfg[sym]["strategy"] not in REGIME_EXEMPT:
                risk_frac *= REGIME_HAIRCUT
            qty = int(self.capital * risk_frac / risk_per_share)
            qty = min(qty, int(self.capital * MAX_WEIGHT / fill))
            # keep total gross notional inside the leverage budget
            room = max(0.0, eq * MAX_GROSS - self.gross())
            qty = min(qty, int(room / fill))
            if entry.side == "long":
                qty = min(qty, int(self.cash / fill))
            if qty < 1:
                return
            self.cash += -qty * fill if entry.side == "long" else qty * fill
            self.positions[sym] = {
                "side": entry.side, "qty": qty, "entry": fill,
                "stop": entry.stop, "target": entry.target, "initStop": entry.stop,
                "strategy": self.cfg[sym]["strategy"], "bucket": self.cfg[sym]["bucket"],
                "opened": self.now().strftime("%H:%M"), "reason": entry.reason,
                "risk": qty * risk_per_share,
            }
            self.say(f"{entry.side.upper()} {qty} {sym} @ ${fill:,.2f} "
                     f"(stop ${entry.stop:,.2f}, target ${entry.target:,.2f}) - {entry.reason}",
                     "good" if entry.side == "long" else "bad")

    def _close(self, sym, px, why):
        with self.lock:
            p = self.positions.pop(sym, None)
            if not p:
                return
            fill = self._fill(px, p["side"], False)
            pl = (fill - p["entry"]) * p["qty"] * (1 if p["side"] == "long" else -1)
            self.cash += p["qty"] * fill if p["side"] == "long" else -p["qty"] * fill
            self.trades.append({
                "sym": sym, "side": p["side"], "qty": p["qty"], "entry": p["entry"],
                "exit": fill, "pl": pl, "plPct": pl / (p["entry"] * p["qty"]) * 100,
                "strategy": p["strategy"], "bucket": p["bucket"],
                "opened": p["opened"], "closed": self.now().strftime("%H:%M"), "why": why,
            })
            self.say(f"CLOSE {sym} @ ${fill:,.2f} - {why} - P/L ${pl:+,.2f}",
                     "good" if pl >= 0 else "bad")

    # ------------------------------------------------------------ management
    def _manage(self, mins):
        for sym in list(self.positions):
            p = self.positions[sym]
            px = self.last_px.get(sym)
            if px is None:
                continue
            long = p["side"] == "long"
            r = abs(p["entry"] - p["initStop"])

            if (long and px <= p["stop"]) or (not long and px >= p["stop"]):
                self._close(sym, p["stop"], "stop hit"); continue
            if (long and px >= p["target"]) or (not long and px <= p["target"]):
                self._close(sym, p["target"], "target hit"); continue

            open_r = ((px - p["entry"]) if long else (p["entry"] - px)) / r if r else 0
            if open_r >= TRAIL_AFTER_R:
                lock = p["entry"] + (px - p["entry"]) * TRAIL_FRAC if long \
                    else p["entry"] - (p["entry"] - px) * TRAIL_FRAC
                if (long and lock > p["stop"]) or (not long and lock < p["stop"]):
                    p["stop"] = round(lock, 4)

        if mins >= S.FLATTEN_AFTER:
            self._flatten("15:55 ET flatten")

    def _flatten(self, why):
        for sym in list(self.positions):
            self._close(sym, self.last_px.get(sym, self.positions[sym]["entry"]), why)

    # ------------------------------------------------------------------ scan
    def _scan(self, mins):
        eq = self.mark()
        if eq / self.capital - 1 <= DAILY_STOP:
            self._flatten("daily loss limit")
            self.status = "halted"
            self.halted_reason = f"daily loss limit {DAILY_STOP:.0%} hit"
            self.say(f"HALTED - {self.halted_reason}. No further entries today.", "bad")
            return
        if mins >= S.NO_NEW_ENTRIES_AFTER or len(self.positions) >= MAX_POSITIONS:
            return

        for sym in self.syms:
            if sym in self.positions:
                continue
            if any(t["sym"] == sym for t in self.trades):   # one shot per name per day
                continue
            ctx = self._ctx(sym)
            if not ctx.ok:
                continue
            cfg = self.cfg[sym]
            entry = S.evaluate(cfg["strategy"], ctx, cfg["params"])
            if entry:
                self._open(sym, entry, ctx.price)
                if len(self.positions) >= MAX_POSITIONS:
                    return

    def _build_scan(self, mins):
        """Per-symbol view of what the engine is currently seeing and waiting for.

        Without this the UI is silent for the first ~20 minutes of the session, which
        looks identical to a dead engine.
        """
        rows = []
        for sym in self.syms:
            cfg = self.cfg[sym]
            p = cfg["params"]
            row = {"sym": sym, "strategy": cfg["strategy"], "side": p["side"],
                   "bucket": cfg["bucket"]}
            done = next((t for t in self.trades if t["sym"] == sym), None)
            ctx = self._ctx(sym)

            if ctx.ok:
                row.update(price=round(ctx.price, 2), gap=round(ctx.gap_pct, 2),
                           chg=round(ctx.chg_pct, 2), vwap=round(ctx.vwap, 2),
                           vsVwap=round((ctx.price / ctx.vwap - 1) * 100, 2),
                           orH=round(ctx.or_high, 2), orL=round(ctx.or_low, 2),
                           bars=ctx.mins)

            if sym in self.positions:
                row.update(state="in position", detail=self.positions[sym]["reason"])
            elif done:
                row.update(state="done", detail=f"traded once today, closed {done['closed']}")
            elif not ctx.ok:
                row.update(state="no data", detail="waiting for the first bars")
            elif ctx.mins < p["or_min"] + 1:
                left = p["or_min"] + 1 - ctx.mins
                row.update(state="warm-up",
                           detail=f"opening range forming, {left} more min")
            elif cfg["strategy"] in ("pead_long", "pead_short", "theme_momo_long",
                                     "theme_momo_short") and ctx.ema21 is None:
                row.update(state="warm-up", detail="2-min EMA21 not seeded yet")
            elif mins >= S.NO_NEW_ENTRIES_AFTER:
                row.update(state="closed", detail="past the 15:00 ET entry cutoff")
            elif len(self.positions) >= MAX_POSITIONS:
                row.update(state="blocked", detail="position limit reached")
            else:
                entry = S.evaluate(cfg["strategy"], ctx, p)
                if entry:
                    row.update(state="signal", detail=entry.reason)
                else:
                    row.update(state="armed", detail=self._why_not(cfg["strategy"], ctx))
            rows.append(row)

        order = {"signal": 0, "in position": 1, "armed": 2, "warm-up": 3,
                 "blocked": 4, "done": 5, "closed": 6, "no data": 7}
        rows.sort(key=lambda r: (order.get(r["state"], 9), r["sym"]))
        self.scan_rows = rows

    @staticmethod
    def _why_not(strategy, c):
        """The single condition currently blocking this rule."""
        if strategy == "orb_long":
            return (f"needs > OR high {c.or_high:.2f}" if c.price <= c.or_high
                    else "needs to hold above VWAP" if c.price < c.vwap
                    else "broke out too far, would be chasing")
        if strategy == "orb_short":
            return (f"needs < OR low {c.or_low:.2f}" if c.price >= c.or_low
                    else "needs to stay below VWAP" if c.price > c.vwap
                    else "broke down too far, would be chasing")
        if strategy in ("pead_long", "theme_momo_long"):
            if c.price <= c.vwap:
                return f"below VWAP {c.vwap:.2f}"
            if c.ema9 is not None and c.ema21 is not None and c.ema9 <= c.ema21:
                return "2-min EMA9 still under EMA21"
            if strategy == "theme_momo_long" and c.ema9 and c.price > c.ema9 * 1.01:
                return "extended, waiting for a pullback to EMA9"
            return "trend not confirmed yet"
        if strategy in ("pead_short", "theme_momo_short"):
            if c.price >= c.vwap:
                return f"above VWAP {c.vwap:.2f}"
            if c.ema9 is not None and c.ema21 is not None and c.ema9 >= c.ema21:
                return "2-min EMA9 still over EMA21"
            if strategy == "theme_momo_short" and c.ema9 and c.price < c.ema9 * 0.99:
                return "extended, waiting for a pullback to EMA9"
            return "trend not confirmed yet"
        if strategy == "gap_fade_short":
            if c.gap_pct < 3:
                return f"gap only {c.gap_pct:+.1f}%, needs >= +3%"
            return "gap still holding, needs to lose VWAP and the OR low"
        if strategy == "gap_fade_long":
            if c.gap_pct > -3:
                return f"gap only {c.gap_pct:+.1f}%, needs <= -3%"
            return "not reclaimed yet, needs VWAP and the OR high"
        if strategy == "mean_rev_long":
            if c.rsi5 is None:
                return "3-min RSI not seeded yet"
            if c.rsi5 >= 32:
                return f"3-min RSI {c.rsi5:.0f}, needs < 32"
            return "oversold, waiting for the first up-tick"
        return "conditions not met"

    def _record(self):
        eq = self.mark()
        bm = self.capital * (1 + self.bench_pct() / 100)
        t = self.now().strftime("%H:%M")
        with self.lock:
            if self.equity and self.equity[-1]["t"] == t:
                self.equity[-1].update(eq=eq, bm=bm)
            else:
                self.equity.append({"t": t, "eq": eq, "bm": bm})

    def _persist(self):
        try:
            with open(STATE_PATH, "w") as f:
                json.dump(self.snapshot(), f)
        except Exception:
            pass
