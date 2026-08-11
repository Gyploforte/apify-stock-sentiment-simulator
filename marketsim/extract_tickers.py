#!/usr/bin/env python3
"""Extract and aggregate ticker mentions from an Apify sentiment dataset.

    python3 extract_tickers.py dataset.json tickers.json

Handles the several forms companies appear in - exchange-prefixed, $CASHTAG, bare
parenthetical, "Company Name - XYZ" - plus a company-name map for the themes the feed
discusses without ever tagging a ticker. The parenthetical pattern alone throws roughly
20% false positives, so everything here is a *candidate* until validated against Yahoo.
"""
import json, re, sys, collections

# Tokens that look like tickers in parentheses but never are.
STOP = set("""CEO CFO COO CTO IPO ETF USA USD EUR GBP JPY CNY INR GDP CPI PPI PMI FED FOMC
SEC FDA FTC DOJ EPS ROI ROE AI ML EV IT US UK EU UAE PR RT NEWS ALERT UPDATE BREAKING NYSE
NASDAQ AMEX LSE TSX ASX HKEX BSE NSE Q1 Q2 Q3 Q4 FY YOY QOQ TTM YTD LLC LTD INC PLC CORP CO
SA AG NV AB AS OY GMBH SPA LP LLP AND THE FOR NOT NEW TOP BIG ALL OUT NOW WHY HOW WHO ONE
TWO OFF PER VS ETC AGM EGM ESG API APIS CFTC IRS EIA OPEC BOJ ECB BOE RBI PBOC SNB WTI LNG
OTC SPAC ADR GDR NAV AUM PE PB PS EBITDA EBIT FCF CAGR LBO DCF WACC MOU LOI NDA SPO FPO QIP
GMP FII DII HNI NRI ULIP SIP AMC NBFC MSME PSU PLI GST TDS ITR PAN KYC UPI ATM POS EMI CIBIL
SEBI IRDAI PFRDA NPS EPF PPF FD RD MF SME ISIN CUSIP SEDOL LEI FIGI RIC MIC WKN BLA SMA ALS
FID H1 H2 1H 2H""".split())

PATTERNS = [
    re.compile(r'\((?:NASDAQ|NYSE|NYSEAMERICAN|NYSE American|AMEX|OTC|OTCMKTS|CBOE|BATS)\s*[:.]\s*([A-Z]{1,5})\)'),
    re.compile(r'\b(?:NASDAQ|NYSE|OTCMKTS|CBOE)\s*:\s*([A-Z]{1,5})\b'),
    re.compile(r'\$([A-Z]{1,5})\b'),
    re.compile(r'\(([A-Z]{1,5})\)'),
    re.compile(r'\b(?:Inc\.?|Corp\.?|Ltd\.?|Co\.?|Company|Corporation|Incorporated|plc|N\.V\.'
               r'|Holdings|Group|Therapeutics|Pharmaceuticals|Technologies|Systems|Solutions'
               r'|Bancorp|Energy|Partners)\s*[-–—]\s*([A-Z]{2,5})\b'),
]

# Themes the feed argues about without tagging tickers. Extend freely - a name only
# survives if Yahoo validates it and it earns a place in the watchlist.
NAME_MAP = {
    "TSMC": "TSM", "Taiwan Semiconductor": "TSM", "Nvidia": "NVDA", "Palantir": "PLTR",
    "Micron": "MU", "Broadcom": "AVGO", "Intel": "INTC", "AMD": "AMD", "Arm Holdings": "ARM",
    "SK hynix": "MU", "Marvell": "MRVL", "Lam Research": "LRCX", "Applied Materials": "AMAT",
    "ASML": "ASML", "KLA": "KLAC", "Snowflake": "SNOW", "Cloudflare": "NET", "Airbnb": "ABNB",
    "Datadog": "DDOG", "CrowdStrike": "CRWD", "MongoDB": "MDB", "Coinbase": "COIN",
    "Circle": "CRCL", "MicroStrategy": "MSTR", "Robinhood": "HOOD", "Core Scientific": "CORZ",
    "Newmont": "NEM", "Barrick": "GOLD", "Freeport": "FCX", "Hecla": "HL", "Coeur": "CDE",
    "Exxon": "XOM", "Chevron": "CVX", "Occidental": "OXY", "Halliburton": "HAL",
    "Schlumberger": "SLB", "Baker Hughes": "BKR", "Devon": "DVN", "Diamondback": "FANG",
    "ConocoPhillips": "COP", "Marathon Petroleum": "MPC", "Valero": "VLO", "Seadrill": "SDRL",
    "Noble": "NE", "Transocean": "RIG", "Pfizer": "PFE", "Eli Lilly": "LLY", "Lilly": "LLY",
    "Merck": "MRK", "Biogen": "BIIB", "Sarepta": "SRPT", "Viatris": "VTRS", "Moderna": "MRNA",
    "Dutch Bros": "BROS", "Parsons": "PSN", "Sezzle": "SEZL", "Bandwidth": "BAND",
    "Perdoceo": "PRDO", "Trulieve": "TCNNF", "SpaceX": "SPCX", "Tesla": "TSLA",
    "Microsoft": "MSFT", "Apple": "AAPL", "Alphabet": "GOOGL", "Google": "GOOGL",
    "Amazon": "AMZN", "Meta Platforms": "META", "Nebius": "NBIS", "CoreWeave": "CRWV",
    "Scholar Rock": "SRRK", "Krystal": "KRYS", "United Airlines": "UAL", "Delta": "DAL",
    "Carnival": "CCL", "Royal Caribbean": "RCL",
}


def main(src, dst):
    data = json.load(open(src))
    agg = collections.defaultdict(
        lambda: {"n": 0, "score": 0.0, "bull": 0, "bear": 0, "neut": 0,
                 "high": 0, "med": 0, "low": 0, "heads": []})

    for rec in data:
        text = rec["content"]
        if text.startswith("META_"):
            continue
        found = set()
        for pat in PATTERNS:
            for m in pat.findall(text):
                if m not in STOP and len(m) >= 2:
                    found.add(m)
        for name, sym in NAME_MAP.items():
            if re.search(r"\b" + re.escape(name), text, re.I):
                found.add(sym)

        score = rec.get("sentiment_score") or 0
        label = rec.get("sentiment") or "neutral"
        impact = rec.get("market_impact") or "low"
        for sym in found:
            a = agg[sym]
            a["n"] += 1
            a["score"] += score
            a[{"bullish": "bull", "bearish": "bear", "neutral": "neut"}[label]] += 1
            a[{"high": "high", "medium": "med", "low": "low"}[impact]] += 1
            if len(a["heads"]) < 6:
                a["heads"].append({"t": text[:190].replace("\n", " "), "s": score,
                                   "i": impact, "at": rec["published_at"]})

    json.dump(dict(agg), open(dst, "w"), indent=1)
    rows = sorted(agg.items(), key=lambda kv: (-kv[1]["n"], -abs(kv[1]["score"])))
    print(f"{len(agg)} candidates -> {dst}\n")
    print(f"{'sym':7}{'n':>4}{'sum':>7}{'avg':>7}  bull/bear/neu  high")
    for k, v in rows[:45]:
        print(f"{k:7}{v['n']:>4}{v['score']:>+7.2f}{v['score']/v['n']:>+7.2f}"
              f"  {v['bull']}/{v['bear']}/{v['neut']:<8}{v['high']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dataset.json",
         sys.argv[2] if len(sys.argv) > 2 else "tickers.json")
