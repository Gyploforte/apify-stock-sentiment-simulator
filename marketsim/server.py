#!/usr/bin/env python3
"""Local web server for the paper-trading simulator. Standard library only.

    python3 server.py            # http://localhost:8777
    python3 server.py --port 9000
"""
import argparse, json, os, sys, threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import engine as E  # noqa: E402

WATCHLIST = json.load(open(os.path.join(HERE, "watchlist.json")))
ENGINE = E.Engine(WATCHLIST)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=os.path.join(HERE, "static"), **kw)

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            return self._json(ENGINE.snapshot())
        if self.path.startswith("/api/watchlist"):
            return self._json(WATCHLIST)
        return super().do_GET()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json({"error": "bad json"}, 400)

        if self.path.startswith("/api/start"):
            cap = float(body.get("capital") or 0)
            if not 1 <= cap <= 1e9:
                return self._json({"error": "capital must be between 1 and 1,000,000,000"}, 400)
            ok, info = ENGINE.start(cap)
            return self._json({"ok": ok, "phase": info, "state": ENGINE.snapshot()})

        if self.path.startswith("/api/stop"):
            ENGINE.stop()
            return self._json({"ok": True, "state": ENGINE.snapshot()})

        return self._json({"error": "unknown endpoint"}, 404)


def load_replay(date, capital):
    """Fill the engine with a completed replay of a past session, so the UI can be
    inspected (and the render path verified) while the market is shut."""
    import backtest
    eng = backtest.run(date, capital, WATCHLIST)
    global ENGINE
    ENGINE = eng
    print(f"  Demo      : replayed {date}, ${capital:,.0f} -> ${eng.mark():,.2f} "
          f"over {len(eng.trades)} trades")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--demo", metavar="YYYY-MM-DD",
                    help="preload a replay of a past session instead of starting idle")
    ap.add_argument("--capital", type=float, default=1000)
    args = ap.parse_args()

    if args.demo:
        load_replay(args.demo, args.capital)

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    phase, mins = E.market_phase()
    print(f"  Watchlist : {len(WATCHLIST['items'])} names for {WATCHLIST['sessionDate']}")
    print(f"  Market    : {phase.upper()} (ET {E.now_et():%H:%M:%S}, {mins:+d} min vs the open)")
    print(f"  Simulator : http://localhost:{args.port}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        ENGINE.stop_flag.set()
        print("\nbye")


if __name__ == "__main__":
    main()
