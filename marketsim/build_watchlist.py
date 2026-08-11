#!/usr/bin/env python3
"""Generate watchlist.json: 50 names, each with a catalyst, a strategy and its parameters.

Inputs are the Apify sentiment aggregate (tickers.json), the Yahoo snapshot (quotes.json)
and the daily-bar technicals (tech.json) produced during research. Those three files live
next to this script; re-running it just re-stamps watchlist.json from them.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))

# sym: (bucket, strategy, catalyst note)
SPEC = [
    # --- A. AI software: the leadership group, but extended -----------------------
    ("TEAM", "AI software",      "orb_long",        "+35.3% Friday on earnings, RSI 75, +50% over the 20-day. Day 2 of a monster gap - require the range break, do not assume continuation."),
    ("ABNB", "AI software",      "orb_long",        "+17.4% on RVOL 4.4 to a 52-week high, RSI 80. Named in the feed alongside NET and SNOW as last week's breakouts."),
    ("PLTR", "AI software",      "theme_momo_long", "+10.3%, RSI 70, +27% over the 20-day, 9 mentions all week. Clean trend - buy pullbacks to EMA9, never the extension."),
    ("MDB",  "AI software",      "orb_long",        "+7.8%, RSI 76. Data infrastructure re-rating with the AI complex."),
    ("SNOW", "AI software",      "orb_long",        "+3.9% but RSI 81 and +15.8% over the 20-day. Very extended; only a genuine range break justifies entry."),
    ("NET",  "AI software",      "theme_momo_long", "+5.6% on RVOL 2.7 to a 52-week high. Trend intact, pullback entry."),
    ("NOW",  "AI software",      "theme_momo_long", "+6.4%, RSI 67, +15.3% over the 20-day. Enterprise AI spend holding up."),

    # --- B. Semiconductors: strongest confirmed theme in the feed -----------------
    ("ONTO", "Semiconductors",   "orb_long",        "+14.7% on RVOL 1.8. Metrology levered to the equipment cycle; South Korea semi equipment investment +75.9%."),
    ("MCHP", "Semiconductors",   "orb_long",        "+13.9% on RVOL 1.7. Analog/MCU recovery - the laggard part of the cycle finally moving."),
    ("NVDA", "Semiconductors",   "theme_momo_long", "+2.3%, RSI 66, +8.3% over the 20-day. 8 mentions. Index-weight anchor for the whole theme."),
    ("TSM",  "Semiconductors",   "theme_momo_long", "Monthly sales +45% year on year - 9 mentions, all bullish, 5 of them high-impact. The single cleanest datapoint in the feed."),
    ("MRVL", "Semiconductors",   "theme_momo_long", "+3.9%, RSI 59, +9.6% over the 20-day. Optical interconnect is the feed's named rotation."),
    ("AMAT", "Semiconductors",   "orb_long",        "+2.2% equipment name, RSI 52 with room. Korea/Taiwan capex is the driver."),
    ("MU",   "Semiconductors",   "orb_long",        "12 mentions, but closed -0.4% with RSI 51 - the feed is louder than the tape. Require the break; ATR 9.7% so size small."),
    ("SNDK", "Semiconductors",   "mean_rev_long",   "-3.7%, RSI 44, -13% under the 20-day while the sector rallies. Laggard reversion, not trend."),

    # --- C. AI infrastructure and power ------------------------------------------
    ("OKLO", "AI power",         "orb_long",        "+14.8% on RVOL 2.5. Datacentre power demand is the second-order AI trade."),
    ("IREN", "AI power",         "theme_momo_long", "+8.7%, +8.8% over the 20-day. Compute capacity re-rating."),
    ("CRWV", "AI power",         "theme_momo_long", "+6.3%, +16% over the 20-day. Note: shorted this on 08-07 and lost 6.09 on it. The tape has since reversed - following it, not defending the old view."),
    ("VRT",  "AI power",         "orb_long",        "-1.0%, RSI 44, still under the 20-day while the group rallies. Needs to prove itself before entry."),

    # --- D. Gold and silver: broke a five-month consolidation ---------------------
    ("NEM",  "Gold / silver",    "theme_momo_long", "+7.2% but RSI 82. Gold broke a five-month base on rate-cut repricing plus Hormuz. Extended - the pullback rule is deliberate."),
    ("AEM",  "Gold / silver",    "theme_momo_long", "+6.5%, RSI 84, +20.9% over the 20-day. Same trade, highest quality producer, same extension problem."),
    ("CDE",  "Gold / silver",    "orb_long",        "+11.1% on RVOL 1.6 with RSI 65 - less extended than the majors, so a breakout entry still has room."),
    ("HL",   "Gold / silver",    "orb_long",        "+6.2%, RSI 65. Silver leverage; MCX silver up on safe-haven demand."),

    # --- E. Oil: the feed and the tape disagree ----------------------------------
    ("XOM",  "Oil divergence",   "orb_long",        "Feed is loudly bullish - crude $85, Hormuz blockade, 55 ships turned away - but XOM closed -1.2% and XLE -1.1%. Bought this narrative on 08-07 and it faded. Require the break."),
    ("HAL",  "Oil divergence",   "mean_rev_long",   "-1.9% with RSI 32, the most oversold name in the complex. If the Hormuz bid is real this is where it shows first."),
    ("VAL",  "Oil divergence",   "orb_long",        "+2.0% offshore driller, one of the few green names in energy. Seadrill raised FY26 guidance."),
    ("VLO",  "Oil divergence",   "orb_short",       "-1.5%, RSI 36, refining margins compressing while crude rises. The short side of the same divergence - deliberately two-sided."),

    # --- F. Crypto: equities up, miners not -------------------------------------
    ("COIN", "Crypto",           "orb_long",        "+5.6% with BTC back over $65K on rate-cut repricing. RSI 46 leaves room."),
    ("CRCL", "Crypto",           "orb_long",        "+5.4% recovering from the Morgan Stanley downgrade that hit it on 08-06."),
    ("MARA", "Crypto",           "theme_momo_short","-5.3%, RSI 40, -12.9% under the 20-day while BTC rallies. Miners are diverging from the coin - that gap usually closes downward."),
    ("CLSK", "Crypto",           "theme_momo_short","-3.5%, -11% under the 20-day. Same miner divergence, same direction."),

    # --- G. Rate-cut beneficiaries ----------------------------------------------
    ("IWM",  "Rate-cut trade",   "theme_momo_long", "+1.1%, RSI 62. Small caps are the cleanest expression of yields falling - Treasury yields fell as the jobs report dashed hike bets."),
    ("XHB",  "Rate-cut trade",   "theme_momo_long", "+1.8% homebuilders, RSI 61. Most rate-sensitive sector in the market."),
    ("KRE",  "Rate-cut trade",   "orb_long",        "-0.4% regional banks, RSI 52 - lagging the rate-cut trade. Needs confirmation."),

    # --- H. Pharma ---------------------------------------------------------------
    ("MRNA", "Pharma",           "orb_long",        "+9.9% with RSI 49 - a large move that has not yet made the name extended."),
    ("PFE",  "Pharma",           "theme_momo_long", "+2.1% on a quarterly beat driven by cancer and heart drugs. RSI 76, low ATR 2.0% so a steady trend vehicle."),
    ("VRTX", "Pharma",           "theme_momo_long", "+2.5%, RSI 60, low volatility. Defensive ballast for a book that is heavily long high-beta."),
    ("LLY",  "Pharma",           "theme_momo_long", "6 mentions, revenue leap noted by analysts. RSI 57 with room."),

    # --- I. Idiosyncratic longs --------------------------------------------------
    ("SPCX", "Idiosyncratic",    "orb_long",        "+15.8% on RVOL 2.8 - Q2 beat plus an Argus upgrade to Buy. 17 mentions, the most-discussed name in the feed."),
    ("BAND", "Idiosyncratic",    "pead_long",       "+11.8% on raised 2026 revenue guidance, yet RSI 32 and still -12% under the 20-day. Room to run without being extended."),
    ("PRDO", "Idiosyncratic",    "pead_long",       "+4.3% on a dividend hike and raised 2026 earnings guidance. Clean, small, uncrowded."),
    ("AMPX", "Idiosyncratic",    "orb_long",        "+5.9%, RSI 60, +14.9% over the 20-day. Energy storage riding the datacentre power theme."),
    ("INTC", "Idiosyncratic",    "orb_long",        "10 mentions but mostly neutral, +1.8%, RSI 54. Highest-uncertainty semi name - only trade the confirmed break."),

    # --- J. Reversal candidates --------------------------------------------------
    ("SEZL", "Reversal",         "gap_fade_long",   "-33.9% on RVOL 7.1 after beating revenue AND raising guidance. Beat-and-raise selloffs are the highest-quality bounce setups; needs to reclaim VWAP and the range high."),
    ("AGO",  "Reversal",         "mean_rev_long",   "-8.7% leaving RSI at 17, the most oversold reading in the universe. Low ATR 2.7% means a tight, cheap stop."),

    # --- K. Idiosyncratic shorts: broken stories, not market bets -----------------
    ("BROS", "Idiosyncratic short","pead_short",    "RSI 20, -17.2% under the 20-day, described in the feed as plummeting all week. Own problem, not a macro bet."),
    ("PSN",  "Idiosyncratic short","pead_short",    "Investor probes widening. RSI 40, -9.7% under the 20-day, ATR 8.8%."),
    ("UTI",  "Idiosyncratic short","orb_short",     "Up 3.9% on the day but RSI 35 and -26.2% under the 20-day on RVOL 2.1 - a bounce inside a broken trend."),
    ("CRL",  "Idiosyncratic short","orb_short",     "RSI 80 and +14.3% over the 20-day with no fresh catalyst in the feed. A failed break here is the cleanest short in the list."),
    ("AYA",  "Idiosyncratic short","orb_short",     "+7.9% leaving RSI 78 and +31.1% over the 20-day. Exhaustion candidate - only if the opening range breaks down."),
]

# Per-strategy defaults. `risk` is the fraction of starting equity risked per trade.
STRATS = {
    "orb_long":         {"side": "long",  "risk": 0.010, "rr": 2.0, "or_min": 15, "desc": "Opening-range breakout long"},
    "orb_short":        {"side": "short", "risk": 0.008, "rr": 2.0, "or_min": 15, "desc": "Opening-range breakdown short"},
    "pead_long":        {"side": "long",  "risk": 0.012, "rr": 2.5, "or_min": 20, "desc": "Post-earnings drift long (hold above VWAP)"},
    "pead_short":       {"side": "short", "risk": 0.010, "rr": 2.5, "or_min": 20, "desc": "Post-earnings drift short (sell VWAP rejections)"},
    "gap_fade_short":   {"side": "short", "risk": 0.008, "rr": 1.5, "or_min": 15, "desc": "Fade an extended gap up, back toward VWAP"},
    "gap_fade_long":    {"side": "long",  "risk": 0.008, "rr": 1.5, "or_min": 15, "desc": "Fade an unconvincing gap down, back toward VWAP"},
    "mean_rev_long":    {"side": "long",  "risk": 0.008, "rr": 1.5, "or_min": 20, "desc": "Oversold (5-min RSI) reversion toward VWAP"},
    "theme_momo_long":  {"side": "long",  "risk": 0.010, "rr": 2.0, "or_min": 15, "desc": "Theme trend long: EMA9>EMA21 above VWAP, buy pullbacks"},
    "theme_momo_short": {"side": "short", "risk": 0.008, "rr": 2.0, "or_min": 15, "desc": "Theme trend short: EMA9<EMA21 below VWAP, sell pullbacks"},
}


def main():
    def load(n):
        p = os.path.join(HERE, n)
        if not os.path.exists(p):
            sys.exit(f"missing {n} - copy the research artefacts next to this script")
        return json.load(open(p))

    tech, quotes, senti = load("tech.json"), load("quotes.json"), load("tickers.json")

    items = []
    for sym, bucket, strat, note in SPEC:
        t, q = tech.get(sym, {}), quotes.get(sym, {})
        s = senti.get(sym)
        items.append({
            "sym": sym,
            "name": t.get("name") or q.get("name") or sym,
            "bucket": bucket,
            "strategy": strat,
            "params": STRATS[strat],
            "note": note,
            "prevClose": t.get("last"),
            "chgPct": round(t.get("chgPct", 0), 2),
            "atr14": t.get("atr14"),
            "atrPct": t.get("atrPct"),
            "rsi14": t.get("rsi14"),
            "rvol": t.get("rvol"),
            "sma20": t.get("sma20"),
            "avgVol20": t.get("avgVol20"),
            "sentimentMentions": (s or {}).get("n", 0),
            "sentimentScore": round((s or {}).get("score", 0.0), 2),
        })

    out = {
        "sessionDate": "2026-08-10",
        "generated": "2026-08-10T07:00Z",
        "source": "Apify lofomachines/social-stock-news-sentiment (992 records, last 24h) + Yahoo Finance",
        "macro": [
            "Regime flipped on Friday's payrolls: -23,000 jobs vs +83,000 expected, with 103,000 of downward revisions. Rate-HIKE bets became rate-CUT bets.",
            "S&P 500 closed at a record 7,758 (+0.62%) on 08-07; best week since April. Treasury yields fell, the dollar is near a two-month low.",
            "Semiconductors lead: TSMC monthly sales +45% y/y, Korean semi equipment investment +75.9%, SK hynix expanding AI memory output.",
            "Gold broke a five-month consolidation on rate-cut repricing plus safe-haven demand; the whole complex closed up 2-11% with RSI 65-84.",
            "DIVERGENCE: the feed is loudly bullish oil (crude $85, US turning away 55 ships at Hormuz) but energy SOLD OFF Friday - XLE -1.1%. Trading the tape, not the story.",
            "CPI lands Wednesday 12 August at 08:30 ET, not today. Monday has no scheduled macro release - but a hot print mid-week is the standing risk to this entire book.",
        ],
        "strategies": STRATS,
        "items": items,
    }
    json.dump(out, open(os.path.join(HERE, "watchlist.json"), "w"), indent=1)
    print(f"wrote watchlist.json with {len(items)} names")
    for b in dict.fromkeys(i["bucket"] for i in items):
        n = [i["sym"] for i in items if i["bucket"] == b]
        print(f"  {b:20} {len(n):2}  {' '.join(n)}")


if __name__ == "__main__":
    main()
