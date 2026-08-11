"""Intraday indicators and the nine strategy rules used by the simulator.

Every strategy is a pure function of a `Ctx` snapshot and returns either None (no
trade) or an `Entry` describing side, stop and target. Exits (stop, target, trail,
time stop, force-flat) are handled generically by the engine, so the rules here only
ever decide *whether to get in*.
"""
import datetime as _dt
import zoneinfo as _zi
from collections import namedtuple

Entry = namedtuple("Entry", "side stop target reason")

_ET = _zi.ZoneInfo("America/New_York")


def _session_open_ts(any_bar_ts):
    """Epoch seconds of 09:30 ET on the day `any_bar_ts` falls in."""
    d = _dt.datetime.fromtimestamp(any_bar_ts, _ET)
    return int(d.replace(hour=9, minute=30, second=0, microsecond=0).timestamp())

# Regular-session minutes, used for the time stop and the flatten deadline.
SESSION_MINUTES = 390
NO_NEW_ENTRIES_AFTER = 330   # 15:00 ET - stop opening new risk in the last half hour
FLATTEN_AFTER = 385          # 15:55 ET


# --------------------------------------------------------------------------- #
# indicators
# --------------------------------------------------------------------------- #
def ema(vals, n):
    if not vals:
        return None
    k = 2 / (n + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(vals, n=14):
    if len(vals) < n + 1:
        return None
    d = [vals[i] - vals[i - 1] for i in range(1, len(vals))][-n:]
    gain = sum(x for x in d if x > 0) / n
    loss = sum(-x for x in d if x < 0) / n
    if loss == 0:
        return 100.0
    return 100 - 100 / (1 + gain / loss)


def resample(bars, factor):
    """Group 1-minute bars into `factor`-minute bars by wall clock.

    Bucketing by timestamp rather than by list position matters for illiquid names,
    where consecutive bars can be many minutes apart - slicing every N entries would
    build a "2-minute bar" out of prints ten minutes apart.
    """
    if not bars:
        return []
    open_ts = _session_open_ts(bars[0]["t"])
    step = factor * 60
    buckets = {}
    for b in bars:
        buckets.setdefault((b["t"] - open_ts) // step, []).append(b)
    out = []
    for k in sorted(buckets):
        chunk = buckets[k]
        out.append({
            "t": open_ts + k * step,
            "o": chunk[0]["o"],
            "h": max(b["h"] for b in chunk),
            "l": min(b["l"] for b in chunk),
            "c": chunk[-1]["c"],
            "v": sum(b["v"] for b in chunk),
        })
    return out


class Ctx:
    """Everything a rule is allowed to look at, derived from session 1-minute bars."""

    def __init__(self, sym, bars, prev_close, atr14, or_min):
        self.sym = sym
        self.bars = bars
        self.prev_close = prev_close
        self.atr = atr14 or 0.0
        self.ok = len(bars) >= 2 and prev_close

        if not self.ok:
            return

        closes = [b["c"] for b in bars]
        self.price = closes[-1]
        self.open_px = bars[0]["o"]
        # Elapsed session time comes from timestamps, never from len(bars). A thin name
        # prints only a handful of bars an hour, and counting bars would both delay its
        # opening range and build that range out of the wrong window.
        open_ts = _session_open_ts(bars[0]["t"])
        self.mins = int((bars[-1]["t"] - open_ts) // 60) + 1
        self.day_high = max(b["h"] for b in bars)
        self.day_low = min(b["l"] for b in bars)
        self.gap_pct = (self.open_px / prev_close - 1) * 100
        self.chg_pct = (self.price / prev_close - 1) * 100

        pv = sum(((b["h"] + b["l"] + b["c"]) / 3) * b["v"] for b in bars)
        vol = sum(b["v"] for b in bars)
        self.vwap = pv / vol if vol else self.price
        self.volume = vol

        # opening range: bars inside the first `or_min` minutes of the session,
        # falling back to the first bar if the name printed nothing in that window
        orb = [b for b in bars if b["t"] < open_ts + or_min * 60] or bars[:1]
        self.or_high = max(b["h"] for b in orb)
        self.or_low = min(b["l"] for b in orb)
        self.or_ready = self.mins > or_min

        # The EMA pair runs on 2-minute bars and the RSI on 3-minute bars. Both are
        # allowed to start once the filter has enough samples to be meaningful rather
        # than a full period - on 5-minute bars a 21-EMA would not exist until 11:15
        # ET, which throws away the most tradeable part of the session.
        b2 = resample(bars, 2)
        c2 = [b["c"] for b in b2]
        self.ema9 = ema(c2[-60:], 9) if len(c2) >= 9 else None
        self.ema21 = ema(c2[-80:], 21) if len(c2) >= 12 else None

        b3 = resample(bars, 3)
        self.rsi5 = rsi([b["c"] for b in b3], 14)
        self.bars5 = b3

    # a floor on stop distance so a quiet tape can't produce a 0.05% stop
    def min_stop(self):
        return max(self.atr * 0.20, self.price * 0.004)


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #
# Fixed R-multiple targets never fired: 0 of 51 trades across four sessions reached one,
# because a 2-2.5R target on a ~1.5% stop needs a 3-5% move while the median favourable
# excursion is +1.16%. Capping target distance by a fraction of the name's own daily ATR
# puts it where price actually goes. The 1R floor keeps reward:risk from inverting.
ATR_TARGET_MULT = 0.30
USE_ATR_TARGETS = True


def _target_dist(c, risk, rr):
    if not (USE_ATR_TARGETS and c.atr):
        return risk * rr
    return max(risk, min(risk * rr, c.atr * ATR_TARGET_MULT))


def _long(c, stop, rr, reason):
    stop = min(stop, c.price - c.min_stop())
    return Entry("long", stop, c.price + _target_dist(c, c.price - stop, rr), reason)


def _short(c, stop, rr, reason):
    stop = max(stop, c.price + c.min_stop())
    return Entry("short", stop, c.price - _target_dist(c, stop - c.price, rr), reason)


def orb_long(c, p):
    if not c.or_ready or c.price <= c.or_high or c.price < c.vwap:
        return None
    if c.price > c.or_high * 1.02:          # too far past the break, chasing
        return None
    return _long(c, c.or_low, p["rr"],
                 f"broke opening range high {c.or_high:.2f} while holding VWAP {c.vwap:.2f}")


def orb_short(c, p):
    if not c.or_ready or c.price >= c.or_low or c.price > c.vwap:
        return None
    if c.price < c.or_low * 0.98:
        return None
    return _short(c, c.or_high, p["rr"],
                  f"broke opening range low {c.or_low:.2f} while capped by VWAP {c.vwap:.2f}")


def pead_long(c, p):
    if not c.or_ready or c.ema9 is None or c.ema21 is None:
        return None
    if not (c.price > c.vwap and c.ema9 > c.ema21 and c.chg_pct > 0):
        return None
    stop = min(c.vwap, c.price - c.atr * 0.6)
    return _long(c, stop, p["rr"],
                 f"post-earnings drift: holding above VWAP {c.vwap:.2f} with 5m EMA9>EMA21")


def pead_short(c, p):
    if not c.or_ready or c.ema9 is None or c.ema21 is None:
        return None
    if not (c.price < c.vwap and c.ema9 < c.ema21 and c.chg_pct < 0):
        return None
    stop = max(c.vwap, c.price + c.atr * 0.6)
    return _short(c, stop, p["rr"],
                  f"post-earnings drift: rejected at VWAP {c.vwap:.2f} with 5m EMA9<EMA21")


def gap_fade_short(c, p):
    if not c.or_ready or c.gap_pct < 3:
        return None
    if not (c.price < c.vwap and c.price < c.or_low):
        return None
    return _short(c, max(c.or_high, c.vwap * 1.005), p["rr"],
                  f"gap +{c.gap_pct:.1f}% failing: lost VWAP and the opening-range low")


def gap_fade_long(c, p):
    if not c.or_ready or c.gap_pct > -3:
        return None
    if not (c.price > c.vwap and c.price > c.or_high):
        return None
    return _long(c, min(c.or_low, c.vwap * 0.995), p["rr"],
                 f"gap {c.gap_pct:.1f}% reclaimed: back above VWAP and the opening-range high")


def mean_rev_long(c, p):
    if not c.or_ready or c.rsi5 is None or len(c.bars5) < 3:
        return None
    if c.rsi5 >= 32 or c.price >= c.vwap:
        return None
    if c.price <= c.bars5[-2]["c"]:          # need the first up-tick
        return None
    return _long(c, c.day_low - c.atr * 0.15, p["rr"],
                 f"5m RSI {c.rsi5:.0f} oversold, turning up off {c.day_low:.2f} toward VWAP {c.vwap:.2f}")


def theme_momo_long(c, p):
    if not c.or_ready or c.ema9 is None or c.ema21 is None:
        return None
    if not (c.price > c.vwap and c.ema9 > c.ema21):
        return None
    if c.price > c.ema9 * 1.01:              # want a pullback, not an extension
        return None
    return _long(c, min(c.vwap * 0.997, c.price - c.atr * 0.5), p["rr"],
                 f"trend long: pullback to 5m EMA9 {c.ema9:.2f} with price above VWAP")


def theme_momo_short(c, p):
    if not c.or_ready or c.ema9 is None or c.ema21 is None:
        return None
    if not (c.price < c.vwap and c.ema9 < c.ema21):
        return None
    if c.price < c.ema9 * 0.99:
        return None
    return _short(c, max(c.vwap * 1.003, c.price + c.atr * 0.5), p["rr"],
                  f"trend short: pullback to 5m EMA9 {c.ema9:.2f} with price below VWAP")


RULES = {
    "orb_long": orb_long,
    "orb_short": orb_short,
    "pead_long": pead_long,
    "pead_short": pead_short,
    "gap_fade_short": gap_fade_short,
    "gap_fade_long": gap_fade_long,
    "mean_rev_long": mean_rev_long,
    "theme_momo_long": theme_momo_long,
    "theme_momo_short": theme_momo_short,
}


def evaluate(strategy, ctx, params):
    if not ctx.ok or ctx.mins < params.get("or_min", 15) + 1:
        return None
    return RULES[strategy](ctx, params)
