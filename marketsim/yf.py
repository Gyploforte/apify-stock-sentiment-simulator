"""Yahoo Finance session helper: cookie + crumb, batched quotes, chart bars.

Shared by the research scripts and the live engine, so every call goes through one
global rate limiter - Yahoo 429s hard on bursts and the limiter is what keeps a
50-symbol refresh loop from tripping it.
"""
import json, time, threading, urllib.request, urllib.parse, http.cookiejar

# NOTE: Yahoo 429s on detailed browser UA strings from a non-browser client.
# The bare "Mozilla/5.0" token is the one that reliably gets through.
UA = 'Mozilla/5.0'
MIN_INTERVAL = 0.45  # seconds between requests, process-wide

_cj = http.cookiejar.CookieJar()
_op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))
_op.addheaders = [('User-Agent', UA)]
_crumb = None
_gate = threading.Lock()
_last_call = [0.0]


def _throttle():
    with _gate:
        wait = MIN_INTERVAL - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()


def _get(url, tries=4):
    last = None
    for i in range(tries):
        _throttle()
        try:
            return _op.open(url, timeout=30).read()
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def crumb():
    global _crumb
    if _crumb is None:
        try:
            _get('https://fc.yahoo.com/', tries=1)  # 404s but sets A1/A3 cookies
        except Exception:
            pass
        _crumb = _get('https://query1.finance.yahoo.com/v1/test/getcrumb').decode()
    return _crumb


def quotes(symbols):
    """Batched quote snapshot. Returns {sym: dict}."""
    out = {}
    c = crumb()
    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i + 50]
        url = ('https://query1.finance.yahoo.com/v7/finance/quote?symbols='
               + urllib.parse.quote(','.join(chunk)) + '&crumb=' + urllib.parse.quote(c))
        j = json.loads(_get(url))
        for r in (j.get('quoteResponse', {}).get('result') or []):
            out[r['symbol']] = r
        time.sleep(0.4)
    return out


def chart(sym, rng='1mo', interval='1d', prepost=True):
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}'
           f'?range={rng}&interval={interval}&includePrePost={"true" if prepost else "false"}')
    j = json.loads(_get(url))
    res = j['chart']['result'][0]
    q = res['indicators']['quote'][0]
    return {
        'meta': res['meta'],
        't': res.get('timestamp', []),
        'o': q.get('open', []), 'h': q.get('high', []),
        'l': q.get('low', []), 'c': q.get('close', []), 'v': q.get('volume', []),
    }
