#!/usr/bin/env python3
"""Render the watchlist + strategy plan as a standalone HTML page."""
import json, html, os

WL = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan.html")

e = html.escape
SIDE = {k: v["side"] for k, v in WL["strategies"].items()}

buckets = {}
for i in WL["items"]:
    buckets.setdefault(i["bucket"], []).append(i)

BUCKET_THESIS = {
    "AI software":        "Last week's leadership, now extended. RSI 75-81 across the group, so every entry demands confirmation rather than a pullback assumption.",
    "Semiconductors":     "The best-evidenced theme in the feed: TSMC sales +45% y/y, Korean equipment capex +75.9%, SK hynix expanding. Broad but not uniform.",
    "AI power":           "The second-order AI trade - datacentre electricity and compute capacity. Higher beta than the chips themselves.",
    "Gold / silver":      "Gold broke a five-month base on rate-cut repricing plus safe-haven demand. Conviction is high, extension is extreme; the pullback rules are deliberate.",
    "Oil divergence":     "The feed says crude $85 and a tightening Hormuz blockade. The tape sold energy on Friday. Deliberately two-sided until one of them is proved right.",
    "Crypto":             "Bitcoin back over $65K on the same rate-cut repricing, but the miners did not follow. Long the equities, short the divergence.",
    "Rate-cut trade":     "Yields fell hard on the payroll miss. Small caps and homebuilders are the most direct expressions of that.",
    "Pharma":             "Lower-volatility ballast for a book that is otherwise long high-beta AI. Real catalysts, modest ATR.",
    "Idiosyncratic":      "Names moving on their own news rather than the market's - the setups least dependent on the regime holding.",
    "Reversal":           "Selloffs with something wrong about them: a beat-and-raise that lost a third of its value, and the most oversold reading in the universe.",
    "Idiosyncratic short":"Broken individual stories, not bets against the market. On 08-07 the thematic shorts lost while the setup-driven one was the best trade of the day.",
}

def rows(items):
    out = []
    for i in items:
        side = SIDE[i["strategy"]]
        chg = i["chgPct"] or 0
        atr = i["atrPct"] or 0
        rsi = i["rsi14"] or 0
        rsi_state = "hot" if rsi >= 70 else "cold" if rsi <= 35 else ""
        out.append(f"""<tr class="r-{side}">
<td class="tk"><span class="sym">{e(i['sym'])}</span><span class="co">{e(i['name'] or '')}</span></td>
<td class="num">{i['prevClose']:.2f}</td>
<td class="num {'up' if chg > 0 else 'down' if chg < 0 else ''}">{chg:+.2f}%</td>
<td class="num"><span class="meter" style="--f:{min(atr / 15, 1):.2f}"></span>{atr:.1f}</td>
<td class="num rsi {rsi_state}">{rsi:.0f}</td>
<td><span class="side s-{side}">{side}</span></td>
<td class="st"><code>{e(i['strategy'])}</code></td>
<td class="why">{e(i['note'])}</td>
</tr>""")
    return "\n".join(out)


sections = []
for b, items in buckets.items():
    longs = sum(1 for i in items if SIDE[i["strategy"]] == "long")
    shorts = len(items) - longs
    bias = ("net long" if longs > shorts else "net short" if shorts > longs else "balanced")
    sections.append(f"""<section class="bucket">
<header class="bh">
  <h3>{e(b)}</h3>
  <p class="thesis">{e(BUCKET_THESIS.get(b, ''))}</p>
  <p class="bmeta"><b>{len(items)}</b> names · {longs}L / {shorts}S · <span class="bias">{bias}</span></p>
</header>
<div class="tw"><table>
<thead><tr><th>Ticker</th><th class="num">Prev</th><th class="num">Chg</th>
<th class="num">ATR%</th><th class="num">RSI</th><th>Side</th><th>Strategy</th><th>Why this name, this rule</th></tr></thead>
<tbody>
{rows(items)}
</tbody></table></div></section>""")

strat_rows = "\n".join(
    f"<tr><td><code>{e(k)}</code></td><td><span class='side s-{v['side']}'>{v['side']}</span></td>"
    f"<td class='num'>{v['risk'] * 100:.1f}%</td><td class='num'>{v['rr']:.1f}R</td>"
    f"<td class='num'>{v['or_min']}m</td><td>{e(v['desc'])}</td>"
    f"<td class='num'>{sum(1 for i in WL['items'] if i['strategy'] == k)}</td></tr>"
    for k, v in WL["strategies"].items())

macro = "\n".join(f"<li>{e(m)}</li>" for m in WL["macro"])

total_l = sum(1 for i in WL["items"] if SIDE[i["strategy"]] == "long")

DOC = f"""<title>Session plan — Monday 10 August 2026</title>
<style>
:root{{
  --paper:#f6f3ec; --panel:#fffdf8; --rule:#ded7c9; --rule2:#ebe5d8;
  --ink:#1b1917; --ink2:#4a453e; --ink3:#8a8377;
  --brass:#8a6320; --brass-w:#f0e6d0;
  --up:#1c6b4c; --down:#a83a2c;
  --serif:ui-serif,Georgia,"Iowan Old Style","Times New Roman",serif;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;
}}
@media (prefers-color-scheme:dark){{
  :root{{--paper:#131318; --panel:#1a1a21; --rule:#2e2e39; --rule2:#24242d;
    --ink:#eae5db; --ink2:#b0a99c; --ink3:#7a7469;
    --brass:#cb9c46; --brass-w:#2a2317; --up:#3fb086; --down:#e4695a;}}
}}
:root[data-theme=dark]{{--paper:#131318; --panel:#1a1a21; --rule:#2e2e39; --rule2:#24242d;
  --ink:#eae5db; --ink2:#b0a99c; --ink3:#7a7469;
  --brass:#cb9c46; --brass-w:#2a2317; --up:#3fb086; --down:#e4695a;}}
:root[data-theme=light]{{--paper:#f6f3ec; --panel:#fffdf8; --rule:#ded7c9; --rule2:#ebe5d8;
  --ink:#1b1917; --ink2:#4a453e; --ink3:#8a8377;
  --brass:#8a6320; --brass-w:#f0e6d0; --up:#1c6b4c; --down:#a83a2c;}}

*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 var(--sans);
  -webkit-font-smoothing:antialiased}}
.page{{max-width:1180px;margin:0 auto;padding:0 24px 90px}}
h1,h2,h3{{font-family:var(--serif);font-weight:600;text-wrap:balance;letter-spacing:-.012em}}

/* masthead */
.mast{{padding:52px 0 22px;border-bottom:2px solid var(--ink)}}
.eyebrow{{font:600 11px/1 var(--mono);letter-spacing:.16em;text-transform:uppercase;
  color:var(--brass);margin-bottom:16px}}
h1{{font-size:clamp(30px,5vw,46px);margin:0 0 10px;line-height:1.08}}
.dek{{font-size:17px;color:var(--ink2);max-width:62ch;margin:0}}
.stamp{{display:flex;flex-wrap:wrap;gap:26px;margin-top:24px;
  font:500 12px/1.4 var(--mono);color:var(--ink3)}}
.stamp b{{display:block;color:var(--ink);font-size:15px;font-weight:600;margin-top:3px;
  font-variant-numeric:tabular-nums}}

/* drivers */
.drivers{{margin:34px 0 10px;padding:24px 26px;background:var(--panel);
  border:1px solid var(--rule);border-left:3px solid var(--brass)}}
.drivers h2{{font-size:13px;font-family:var(--mono);font-weight:600;letter-spacing:.14em;
  text-transform:uppercase;color:var(--brass);margin:0 0 14px}}
.drivers ol{{margin:0;padding-left:20px;color:var(--ink2);font-size:15px}}
.drivers li{{margin-bottom:9px}} .drivers li:last-child{{margin-bottom:0}}
.drivers li::marker{{color:var(--ink3);font:600 12px var(--mono)}}

h2.sec{{font-size:26px;margin:56px 0 6px;padding-top:26px;border-top:1px solid var(--rule)}}
.lede{{color:var(--ink2);margin:0 0 22px;max-width:66ch}}

/* buckets */
.bucket{{margin-bottom:38px}}
.bh{{display:grid;grid-template-columns:1fr auto;gap:4px 24px;align-items:baseline;
  padding-bottom:10px;border-bottom:1px solid var(--rule)}}
.bh h3{{margin:0;font-size:19px}}
.thesis{{grid-column:1;margin:2px 0 0;color:var(--ink2);font-size:14px;max-width:78ch}}
.bmeta{{grid-column:2;grid-row:1;margin:0;font:12px var(--mono);color:var(--ink3);white-space:nowrap}}
.bmeta b{{color:var(--ink)}}
.bias{{color:var(--brass);font-weight:600}}

.tw{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;font:600 10px/1.5 var(--mono);letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink3);padding:10px 10px 8px;border-bottom:1px solid var(--rule);white-space:nowrap}}
td{{padding:11px 10px;border-bottom:1px solid var(--rule2);vertical-align:top}}
tbody tr:last-child td{{border-bottom:0}}
.num{{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap}}
.tk{{min-width:150px}}
.sym{{display:block;font:700 14px var(--mono);letter-spacing:.02em}}
.co{{display:block;font-size:11px;color:var(--ink3);line-height:1.35;margin-top:1px}}
.up{{color:var(--up)}} .down{{color:var(--down)}}
.rsi.hot{{color:var(--down)}} .rsi.cold{{color:var(--up)}}
.meter{{display:inline-block;width:26px;height:3px;background:var(--rule);
  margin-right:7px;vertical-align:middle;position:relative}}
.meter::after{{content:"";position:absolute;inset:0 auto 0 0;width:calc(var(--f)*100%);
  background:var(--brass)}}
.side{{display:inline-block;font:600 9.5px/1 var(--mono);letter-spacing:.1em;
  padding:4px 7px;border:1px solid currentColor;text-transform:uppercase}}
.s-long{{color:var(--up)}} .s-short{{color:var(--down)}}
.st code{{font:12px var(--mono);color:var(--ink)}}
.why{{color:var(--ink2);font-size:12.5px;line-height:1.55;min-width:270px;max-width:44ch}}
.r-long .tk{{box-shadow:inset 2px 0 0 var(--up)}}
.r-short .tk{{box-shadow:inset 2px 0 0 var(--down)}}

/* reference tables */
.ref table td{{font-size:13px}}
.ref code{{font:12px var(--mono);color:var(--brass)}}
.risk{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:1px;
  background:var(--rule);border:1px solid var(--rule);margin-top:20px}}
.risk div{{background:var(--panel);padding:15px 17px}}
.risk dt{{font:600 10px/1.4 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--ink3)}}
.risk dd{{margin:5px 0 0;font:600 17px var(--mono);font-variant-numeric:tabular-nums}}

.caveat{{margin-top:46px;padding:20px 24px;border:1px solid var(--rule);
  background:var(--brass-w);font-size:14px;color:var(--ink2)}}
.caveat b{{color:var(--ink)}}
footer{{margin-top:34px;padding-top:18px;border-top:1px solid var(--rule);
  font:11px/1.7 var(--mono);color:var(--ink3)}}
@media(max-width:640px){{.bh{{grid-template-columns:1fr}}.bmeta{{grid-column:1;grid-row:auto}}}}
</style>

<div class="page">
<div class="mast">
  <p class="eyebrow">Pre-market research note · paper trading only</p>
  <h1>Session plan for Monday, 10 August 2026</h1>
  <p class="dek">Fifty names pulled out of 992 scored social and news signals from the last
  24 hours, sorted into eleven catalyst buckets, each with one intraday rule and a stop
  defined before the open.</p>
  <div class="stamp">
    <div>Signals scored<b>992</b></div>
    <div>Tickers found<b>143 → 209 validated</b></div>
    <div>Watchlist<b>50 names</b></div>
    <div>Direction<b>{total_l}L / {50 - total_l}S</b></div>
    <div>Cash equities open<b>09:30 ET</b></div>
  </div>
</div>

<div class="drivers">
  <h2>What moves the tape today</h2>
  <ol>{macro}</ol>
</div>

<h2 class="sec">The watchlist</h2>
<p class="lede">Grouped by catalyst rather than by sector, because on a single session the
catalyst — not the industry — is what the price is actually reacting to. <b>Prev</b> is the
07 August close, <b>Chg</b> that session's move, <b>ATR%</b> the 14-day average range as a
share of price, which is what sets position size.</p>

{"".join(sections)}

<h2 class="sec">The nine rules</h2>
<p class="lede">Each rule only decides whether to enter. Stops, targets, trailing, the time
stop and the 15:55 flatten are handled identically for all fifty names, so risk behaviour
never varies by strategy. <b>Risk</b> is the share of starting equity put at risk per trade;
<b>R:R</b> the reward multiple on that risk; <b>Warm-up</b> how long after the open the rule
may first fire.</p>
<div class="ref tw"><table>
<thead><tr><th>Rule</th><th>Side</th><th class="num">Risk</th><th class="num">R:R</th>
<th class="num">Warm-up</th><th>Entry condition</th><th class="num">Names</th></tr></thead>
<tbody>{strat_rows}</tbody></table></div>

<h2 class="sec">Risk model</h2>
<p class="lede">Every constraint below is enforced by the engine, not by discipline. The
kill switch matters most: the CPI print on Wednesday can invalidate every thesis on this
page at once, which is exactly what the payroll print did on 07 August.</p>
<div class="risk">
  <div><dt>Risk per trade</dt><dd>0.8–1.2%</dd></div>
  <div><dt>Max position</dt><dd>18% of equity</dd></div>
  <div><dt>Max concurrent</dt><dd>10 positions</dd></div>
  <div><dt>Max gross exposure</dt><dd>1.5×</dd></div>
  <div><dt>Trades per name</dt><dd>1 / day</dd></div>
  <div><dt>Slippage charged</dt><dd>5 bps each way</dd></div>
  <div><dt>Trail past +1R</dt><dd>50% of open profit</dd></div>
  <div><dt>Last new entry</dt><dd>15:00 ET</dd></div>
  <div><dt>Force flat</dt><dd>15:55 ET</dd></div>
  <div><dt>Daily kill switch</dt><dd>−8%</dd></div>
</div>

<div class="caveat">
  <b>This is a research exercise, not investment advice.</b> The strategies are written to be
  executed by a paper-trading simulator against delayed Yahoo Finance prices; no order
  reaches a broker. Sentiment scores come from a third-party feed and were not
  independently verified name by name. Position sizing assumes fills at the touch, which
  real markets do not guarantee — least of all in the first fifteen minutes, which is
  exactly when most of these rules fire.
</div>

<footer>
  Signals: Apify <code>lofomachines/social-stock-news-sentiment</code>, last_24h sweep, 992 unique records (496 from 09 Aug, 496 from 10 Aug UTC).<br>
  Prices, technicals and validation: Yahoo Finance. Macro context: CNBC, FactSet, Kiplinger, OilPrice, Al Jazeera, CME FedWatch.<br>
  Generated 10 Aug 2026, 07:00 UTC.
</footer>
</div>
"""

# Emit every non-ASCII glyph as a numeric entity so the page renders identically
# regardless of what charset the host declares.
DOC = "".join(c if ord(c) < 128 else f"&#{ord(c)};" for c in DOC)
open(OUT, "w", encoding="ascii").write(DOC)
print("wrote", OUT, len(DOC), "bytes, ascii-safe")
