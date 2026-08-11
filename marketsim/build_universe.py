#!/usr/bin/env python3
"""Validate ticker candidates against Yahoo and compute daily-bar technicals.

    python3 build_universe.py            # reads tickers.json, writes quotes.json + tech.json

Candidates come from extract_tickers.py; THEME_EXTRA adds the names the feed argues
about without ever tagging a symbol. Everything is filtered to real US-listed equities
(or ETFs, for benchmarks) before it can reach the watchlist.
"""
import json, os, sys, time
import yf

HERE = os.path.dirname(os.path.abspath(__file__))

# Themes discussed in the feed without ticker tags, plus liquid expressions of each.
THEME_EXTRA = """
TSM MU NVDA AMD AVGO INTC ARM MRVL LRCX AMAT KLAC ASML SNDK VECO MXL ONTO TER SMCI
PLTR SNOW NET DDOG MDB CRWD ABNB TEAM NOW ORCL
CRWV NBIS VRT IREN CEG OKLO SMR GEV ETN PWR
NEM GOLD AEM HL CDE PAAS AG WPM RGLD FCX SCCO
XOM CVX OXY SLB HAL BKR DVN FANG COP MPC VLO PSX SDRL RIG NE VAL WFRD
COIN MSTR MARA RIOT HOOD CRCL CORZ CLSK
PFE LLY MRK BIIB SRPT VTRS MRNA KRYS SRRK VRTX ABBV AMGN
BAND PRDO SEZL BROS PSN SPCX TCNNF AMPX FFAI ORGO HUBS TJX SHW ROK CNMD
UAL DAL AAL LUV CCL RCL
SPY QQQ IWM DIA GLD SLV USO TLT XLE XLF XLK XLV KRE XHB SMH
""".split()


def snap(r, sym):
    return {
        "sym": sym,
        "name": r.get("longName") or r.get("shortName"),
        "exch": r.get("fullExchangeName"),
        "quoteType": r.get("quoteType"),
        "price": r.get("regularMarketPrice"),
        "prevClose": r.get("regularMarketPreviousClose"),
        "chgPct": r.get("regularMarketChangePercent"),
        "avgVol": r.get("averageDailyVolume3Month"),
        "mcap": r.get("marketCap"),
        "w52h": r.get("fiftyTwoWeekHigh"), "w52l": r.get("fiftyTwoWeekLow"),
        "w52ChgPct": r.get("fiftyTwoWeekChangePercent"),
        "sma50": r.get("fiftyDayAverage"), "sma200": r.get("twoHundredDayAverage"),
        "trailPE": r.get("trailingPE"), "epsDate": r.get("earningsTimestamp"),
    }


def atr(h, l, c, n=14):
    trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
           for i in range(1, len(c))]
    return sum(trs[-n:]) / min(n, len(trs)) if trs else 0.0


def rsi(c, n=14):
    d = [c[i] - c[i - 1] for i in range(1, len(c))][-n:]
    g = sum(x for x in d if x > 0) / n
    l = sum(-x for x in d if x < 0) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def main():
    cands = json.load(open(os.path.join(HERE, "tickers.json")))
    syms = sorted(set(cands) | set(THEME_EXTRA))
    print(f"validating {len(syms)} symbols ({len(cands)} from the feed, "
          f"{len(set(THEME_EXTRA) - set(cands))} theme additions)")

    q = yf.quotes(syms)
    good, bad = {}, []
    for s in syms:
        r = q.get(s)
        ok = (r and r.get("regularMarketPrice") is not None
              and r.get("currency") == "USD"
              and r.get("quoteType") in ("EQUITY", "ETF", "INDEX")
              and r.get("fullExchangeName") not in ("Other OTC", "OTC Markets"))
        (good.setdefault(s, snap(r, s)) if ok else bad.append(s))

    json.dump(good, open(os.path.join(HERE, "quotes.json"), "w"), indent=1)
    print(f"valid: {len(good)}   rejected: {len(bad)}")
    print("rejected:", " ".join(bad))

    # Technicals only for names liquid enough to trade intraday.
    tradable = [s for s, v in good.items()
                if (v["avgVol"] or 0) * (v["price"] or 0) > 15e6 and (v["price"] or 0) > 3]
    print(f"\ncomputing technicals for {len(tradable)} liquid names")

    tech = {}
    for s in sorted(tradable):
        try:
            ch = yf.chart(s, "3mo", "1d", prepost=False)
            rows = [r for r in zip(ch["o"], ch["h"], ch["l"], ch["c"], ch["v"])
                    if None not in r[:4]]
            o, h, l, c = ([r[i] for r in rows] for i in range(4))
            v = [r[4] or 0 for r in rows]
            if len(c) < 25:
                continue
            a = atr(h, l, c)
            tech[s] = {
                "sym": s, "name": ch["meta"].get("longName") or ch["meta"].get("shortName"),
                "last": c[-1], "prev": c[-2], "chgPct": (c[-1] / c[-2] - 1) * 100,
                "atr14": round(a, 4), "atrPct": round(a / c[-1] * 100, 2),
                "rsi14": round(rsi(c), 1),
                "sma20": round(sum(c[-20:]) / 20, 4), "sma50": round(sum(c[-50:]) / min(50, len(c)), 4),
                "vol": v[-1], "avgVol20": int(sum(v[-20:]) / 20),
                "rvol": round(v[-1] / (sum(v[-21:-1]) / 20), 2) if sum(v[-21:-1]) else 0,
                "hi20": max(h[-20:]), "lo20": min(l[-20:]),
                "vs20d": round((c[-1] / (sum(c[-20:]) / 20) - 1) * 100, 2),
            }
        except Exception as e:
            print(f"  ! {s}: {type(e).__name__}")
        time.sleep(0.05)

    json.dump(tech, open(os.path.join(HERE, "tech.json"), "w"), indent=2)
    print(f"wrote tech.json with {len(tech)} names")


if __name__ == "__main__":
    main()
