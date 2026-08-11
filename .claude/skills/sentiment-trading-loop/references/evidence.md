# What results license you to change

Read this before concluding anything from a session's P/L. The whole point of the loop is
that intraday results are mostly noise, and the natural human response to noise — adjust
something — is what destroys a strategy.

## 1. Look-ahead contamination

A watchlist built on day *D* using day *D*'s closing data and news **cannot be evaluated on
day *D***. It will look good, and the result means nothing.

Concretely, from the reference run: CELH was assigned a short because it fell 18.5% *that
day*. REPL was on the list because of an FDA approval announced *after* that day's close.
Backtesting the list on that same day produced +0.88%. Backtesting it on the following,
genuinely unseen session produced −1.18%. The first number is not a worse estimate than
the second — it is not an estimate of anything.

**Rule.** The only sessions that count as evidence are those strictly after the watchlist
was frozen. Everything else is a smoke test that the code runs. When reporting to the user,
label each number as in-sample or out-of-sample every single time. If you gave them a
contaminated number earlier in the conversation, correct it explicitly rather than quietly
replacing it — they may have already reasoned from it.

A subtler version: technical filters (ATR, RSI, RVOL) computed from day *D*'s close leak
into day *D* too. Days further from the selection date are less contaminated, never more.

## 2. Sample size, honestly

A session produces 10–20 trades. That is not a sample you can tune on.

Rough orientation, assuming per-trade returns with a ~2% standard deviation:

| Trades | What you can distinguish |
| --- | --- |
| ~15 (one session) | Whether the code ran. Nothing about edge |
| ~50 (a week) | Gross structural defects — a parameter that never fires, a rule that never triggers |
| ~200 (a quarter) | Whether the whole book beats the benchmark, roughly |
| ~500+ | Whether one rule beats another |

A strategy with a genuine 55% hit rate loses money on a fifth of its weeks. A strategy with
no edge has winning weeks constantly. Neither fact is visible from four sessions.

**Rule.** Before proposing a parameter change, state how many out-of-sample trades support
it. If the answer is under 50, the honest recommendation is usually "keep collecting" — and
saying so is more useful than a confident tweak.

## 3. The one exception: structural defects

Some findings do not depend on sample size, because they are about **mechanism**, not
performance. These are safe to act on immediately:

- A parameter that never binds. 0 of 51 target exits is not an unlucky streak; it means the
  target is unreachable given the position's own stop distance and the instrument's range.
  Arithmetic, not statistics.
- A code path that never executes.
- An exposure the plan did not intend — discovering the book is 2x gross or structurally
  short beta.
- A stated risk with no corresponding mechanism, e.g. identifying a scheduled macro release
  as the plan's largest threat while having nothing that responds to it.

The test for whether a finding is structural: **could you have found it without knowing the
P/L?** If yes, act. If the finding is "this rule lost money", that is performance, and
performance needs sample size.

## 4. Mean and median

Small books are dominated by outliers, and the mean will tell you the opposite of the truth.

From the reference session's six short trades: mean return **+1.35%**, median **−1.84%**. The
mean was entirely one trade at +15.3%. A reader shown only the mean concludes the short book
worked; a reader shown only the median concludes it failed. Both are over-reading.

**Rule.** Report both, always, and when they disagree say so explicitly rather than picking
the one that fits the narrative. Name the outlier.

## 5. Separate the thesis from the machinery

Every session's outcome decomposes into at least three things:

1. **Was the regime call right?** (Was the market up or down, and was the book positioned for it?)
2. **Was the name selection right?** (Did the chosen names move as the catalyst implied?)
3. **Did the rules capture the move?** (MFE tells you the move was there; P/L tells you whether the rule got it.)

These need different fixes and get conflated constantly. A day where the index rose 1.4%
and a net-short book lost is a regime failure — changing the entry rules would be treating
the wrong organ.

MFE is the key discriminator. A trade with a large favourable excursion that still lost is
an *exit* problem. A trade whose best moment was +0.07% never worked at all, which is an
*entry or selection* problem.

## 6. Changing one thing at a time

When a change is justified:

1. State the hypothesis and what would falsify it, before running anything.
2. Change exactly one parameter.
3. Re-run every available session, and report in-sample and out-of-sample separately.
4. Report the result even when it contradicts the hypothesis — especially then.
5. Keep the change only if it helps out-of-sample, or if it is a structural fix from §3.

Re-tuning on the same sessions you diagnosed from is in-sample by construction. It will
almost always look like an improvement. Label it as such and treat it as a smoke test.

## 7. Reporting to the user

They are making decisions about money with these numbers, so:

- Lead with the number, not the narrative.
- Say which sessions are contaminated, every time.
- Give the benchmark alongside every return figure.
- When the sample cannot support a conclusion, say that plainly instead of hedging a
  confident-sounding answer. "Fourteen trades cannot distinguish this from noise" is a
  complete and useful answer.
- If asked to "improve the model" after a loss, resist producing a tuned parameter set.
  Explain what the evidence supports, fix any structural defects, and say what would need
  to accumulate before tuning is meaningful. That is the more valuable answer, even though
  it is less satisfying than a fix.
