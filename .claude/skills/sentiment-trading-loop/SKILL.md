---
name: sentiment-trading-loop
description: Research loop for building intraday trading watchlists from social/news sentiment and evaluating them honestly. Use this whenever the user wants to turn sentiment or news data into a stock watchlist, assign trading strategies to tickers, run or extend the marketsim paper-trading simulator, review how a past trading session performed, or decide whether a strategy change is justified by results. Also use it whenever the user asks to "improve the model", "tune the strategy", or "make it more predictive" after seeing session results — the anti-overfitting discipline here is the main reason this skill exists.
---

# Sentiment-driven intraday trading research loop

This is a **closed loop**, not a one-shot analysis. The interesting part is not building
a watchlist — that is the easy half. The hard half is stage 6, where you decide what a
session's results actually license you to change. Almost every failure mode in this
workflow is a premature conclusion drawn from too few trades.

Paper trading only. Fills are simulated in-process; nothing reaches a broker, and adding
order routing is a different product that needs to be asked for explicitly.

## The loop

```
1 collect → 2 extract & validate → 3 select → 4 assign strategies
                    ↑                                    ↓
                    └──────── 6 post-mortem ←──── 5 simulate
```

Stage 6 feeds stage 3 and 4. Running 1–5 repeatedly without 6 just generates watchlists.

---

## Stage 1 — Collect

Run the Apify actor `lofomachines/social-stock-news-sentiment`. It sweeps news outlets,
Telegram, X and Reddit, deduplicates, and scores each item.

The run takes ~2.5 minutes. Poll with `get-actor-run` rather than assuming it finished.

### The Actor's contract

Read this before writing any analysis code against the dataset. Guessing a field name or
assuming the sentiment fields are populated are the two ways this stage fails silently.

**Inputs**

| Field | Type | What to pass |
| --- | --- | --- |
| `timeRange` | enum: `last_hour` \| `last_24h` | `last_24h` for the pre-market sweep. `last_hour` is the intraday refresh — use it when re-checking a thesis mid-session, not when building the watchlist |
| `maxItems` | integer, **minimum 1000** | `1000`. Coverage is spread across sources, so a lower number does not simply truncate — it thins every source |
| `sentiment` | boolean, default `true` | `true`. **Paid Apify plans only** — see below |

**Outputs** — nine flat fields per record, no nesting:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | 16-char stable identifier |
| `content` | string | The signal text. **Not uniform** — see below |
| `content_length` | integer | Character count |
| `word_count` | integer | Median ~13 |
| `published_at` | string | ISO-8601 UTC, e.g. `2026-08-10T03:50:11Z` |
| `published_date` | string | `YYYY-MM-DD`, derived from `published_at` |
| `sentiment` | string \| **null** | `bullish` \| `bearish` \| `neutral` |
| `sentiment_score` | float \| **null** | Observed range −0.9 to +0.9; the schema allows −1.0 to +1.0 |
| `market_impact` | string \| **null** | `high` \| `medium` \| `low` |

**On a free Apify plan the last three fields are `null`** and no content is sent for
scoring. Every other field is unaffected. Check for nulls before aggregating — averaging a
null column yields zero, which reads as "perfectly neutral market" and is entirely wrong.
If the sentiment fields are null, fall back to selecting on impact-free volume and price
action, and say so in the plan.

### What to expect in the data

Measured across two reference runs (2026-08-07 and 2026-08-10), both `last_24h`,
`maxItems: 1000`, ~1,000 records each, billed at $0.053 per run:

- **About half the records carry the previous calendar date.** A `last_24h` sweep run at
  07:00 UTC split 555/445 and 496/496 across the two dates. This is correct behaviour, not
  stale data — the previous US session and its after-hours reaction are the point.
- **`content` ranges from a 2-word fragment to a 1,527-word article.** In one run 853 of 992
  records were headlines under 25 words and 41 were full articles. Any text analysis has to
  handle both; truncating uniformly throws away the long-form context.
- **Some runs include `META_`-prefixed placeholder records** such as `META_TITLE_SECTORS`.
  They carry no signal. Skip anything where `content.startswith("META_")` — one reference
  run had them, the other had none.
- **Near-duplicates are normal.** The same story arrives from several sources, typically
  2×. Deduplicating on the first ~70 characters is usually enough; do not assume `id`
  uniqueness means story uniqueness.
- **Not everything is in English.** One run carried 15 Finnish and Danish records. Ticker
  extraction and any keyword matching will miss these; that is acceptable, silently
  dropping them without noticing is not.
- **The bullish/bearish ratio shifts run to run, and the shift is itself a signal.** The two
  reference runs came in at 302/241 (1.25) and 375/190 (1.97). The second followed an
  overnight repricing of Fed expectations. Compare the ratio to the previous run before
  reading any individual record.

**Pull the dataset over plain HTTP, not through the MCP tool** — Apify datasets are
publicly readable by ID and the payload is ~600 KB, which will swamp the context window
if returned inline:

```bash
curl -s -o dataset.json "https://api.apify.com/v2/datasets/<DATASET_ID>/items?clean=true&format=json"
```

Then analyse it with a script. Never read 1000 records into context to count sentiment.

## Stage 2 — Extract and validate tickers

Records mention companies in several forms, and you need all of them or you will miss
most of the feed: `(NASDAQ: XYZ)`, `$XYZ`, bare `(XYZ)`, `Company Name - XYZ`, and plain
company names with no ticker at all. Expect roughly a 20% false-positive rate from the
parenthetical pattern alone — `(CEO)`, `(IPO)`, `(GDP)` all look like tickers.

Validate every candidate against Yahoo before trusting it. Filter to `quoteType == EQUITY`,
`currency == USD`, and drop OTC listings. In the reference run this took 159 candidates
down to 126 real US-listed equities.

The feed also discusses themes without tagging tickers — oil, metals, airlines, crypto.
Map those to symbols manually and add them; on the reference day the strongest single
theme (a Hormuz supply shock) had almost no tagged tickers at all.

**Treat the sentiment scores as a candidate-surfacing device, not as ground truth.** They
come from a third party and some records reference companies that cannot be corroborated.
Ground every price, technical and sizing decision in market data instead.

## Stage 3 — Select the watchlist

Group by **catalyst, not sector**. Within a single session the catalyst is what price is
reacting to; two semiconductor names with different catalysts behave nothing alike, while
an airline and a cruise line sharing a fuel-cost shock behave identically.

Filter on liquidity ($ADV and price) and keep volatility high enough that intraday rules
have room to work — a name with a 1% ATR cannot pay for a 0.4% stop plus slippage.

Record per name: the catalyst in one sentence, prev close, day change, ATR%, RSI, RVOL,
and the sentiment aggregate. `marketsim/build_watchlist.py` emits this as `watchlist.json`.

**Count your independent bets, not your names.** Fifty names in twelve buckets where seven
are long oil and three are short airlines is not fifty bets — it is one macro bet with
ten expressions. Check the net and gross exposure implied by the list before the open.

## Stage 4 — Assign strategies

One rule per name, chosen from that name's actual setup rather than applied uniformly.
The nine rules live in `marketsim/strategies.py` (opening-range breakout/breakdown,
post-earnings drift long/short, gap fade both ways, oversold reversion, trend momentum
both ways).

Each rule decides only **whether to enter**. Stops, targets, trailing, the time stop and
the forced flatten are handled generically in `engine.py`, so risk behaviour is identical
across every name and a bad session can never be blamed on one rule's exit logic.

Write the reasoning down at assignment time, in the watchlist file. At post-mortem you
need to distinguish "the thesis was wrong" from "the thesis was right and the rule missed
it", and you cannot reconstruct that afterwards from a P/L column.

## Stage 5 — Simulate

`python3 marketsim/server.py` and press Start. If the market is shut the engine arms and
begins at 09:30 ET on its own.

Replay any past session through the identical engine — only the clock and bar feed are
swapped:

```bash
python3 marketsim/backtest.py --date YYYY-MM-DD --capital 1000
```

A replay that tracks a live run closely is the evidence that the replay is trustworthy.
On the reference session the two agreed within $1 at the point the live run stopped.

---

## Stage 6 — Post-mortem

This is the stage that makes the loop worth running. Read `references/evidence.md`
before drawing any conclusion from results — it covers contamination, sample size, and
which changes a given amount of evidence licenses.

Run the diagnostic battery:

```bash
python3 scripts/diagnose.py <marketsim-dir> YYYY-MM-DD [YYYY-MM-DD ...]
```

It reports, per session and pooled:

| Diagnostic | What it catches |
| --- | --- |
| Exit-reason census | Dead exits. A target that never fires is a broken parameter, not bad luck |
| MAE / MFE per trade | Whether stops are too tight, or entries are simply late |
| Best-ever excursion on stopped trades | Trades that never worked at all vs. ones that worked then reversed |
| Mean **and median** trade return | One outlier can invert the mean of a small book |
| Index move over each hold | Whether the day was beta, not skill |
| Bucket concentration | How many bets there really were |
| Gross and net exposure | Structural directional bias you did not intend |

Report mean and median side by side, always. With ten to twenty trades they routinely
disagree, and the mean is the one that lies.

### The benchmark

The S&P 500 is the benchmark, measured **from the opening print, not the prior close**.
The portfolio starts flat at 09:30 and is flat by 15:55, so it never holds the overnight
gap. On the reference session that distinction was worth 0.36 pp — the index closed
+0.62% but was only +0.26% from the open, because most of the day's move arrived in the
gap. Charging the close-to-close number against an intraday book compares two different
exposures and will make a flat strategy look bad or a bad one look flat.

---

## Data-layer traps

These cost real debugging time. They are not obvious and they fail quietly.

**Yahoo rejects realistic User-Agents.** A full Chrome UA string from a non-browser client
gets HTTP 429; the bare token `Mozilla/5.0` gets through. Bursts also trip it — roughly
16 concurrent requests is too many, ~0.45s between requests process-wide is safe.
`marketsim/yf.py` already encodes this, plus the cookie/crumb dance the batched quote
endpoint needs. Use it rather than writing a fresh client.

**Never use `len(bars)` as elapsed minutes.** A thin name prints a handful of bars an
hour. Counting bars both delays its opening range and builds that range from the wrong
window — the first 15 *prints* can span an hour. Derive elapsed time from timestamps, and
select the opening range by `bar["t"] < open_ts + or_min * 60`.

**Resample by wall clock, not list position.** Slicing every N entries builds a
"2-minute bar" out of prints ten minutes apart on illiquid names, silently corrupting
every EMA and RSI computed from it.

**Short positions need explicit accounting.** If short proceeds are credited to cash at
open, the short leg must be *subtracted* in mark-to-market or the position is counted
twice. The symptom is spectacular: equity on a $1,000 account spiking to $1,853 with no
corresponding trades.

---

## Open defects in the current implementation

Carried forward from the reference sessions. Fix them deliberately, one at a time, and
measure each in isolation — see `references/evidence.md` for how.

1. **Profit targets are unreachable.** 0 of 51 trades across four sessions hit target;
   69% simply ran to the 15:55 flatten. Targets sit at 2.0–2.5R, which on a ~1.5% stop
   needs a 3–5% move, while the median favourable excursion is +1.16%. The fix direction
   is to scale targets from the name's own realised intraday range rather than a fixed R
   multiple — but that is a hypothesis, and it needs out-of-sample sessions to confirm.

2. **No regime gate.** The reference plan was built on a hawkish-Fed thesis ~2.5h before
   the open. The 08:30 employment print inverted that thesis twelve minutes before the
   bell and the system executed the plan unchanged, into the exact names the new regime
   favoured. A scheduled macro release that the plan itself identifies as its largest risk
   should be able to veto or halve the book. Nothing currently connects the two.

3. **Sizing dispersion.** Risk-per-share sizing produced 1 share of one name and 16 of
   another, so session P/L is dominated by which names happened to get large share counts
   rather than by which theses were right. Worth measuring before it is worth fixing.
