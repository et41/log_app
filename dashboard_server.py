"""
Local TÜRKAK dashboard: serves test-raporu-defteri.html on
http://127.0.0.1:8080 and keeps its "Live file access" panel fresh by running
file_access_collector every COLLECT_INTERVAL_SECONDS in the background. The
page polls file_access_live.json, so new accesses show up within seconds.

Must run in an elevated (Run as administrator) prompt, since the collector
reads the Windows Security log.

  python dashboard_server.py              # http://127.0.0.1:8080
  python dashboard_server.py --port 9000

Only the files in ROUTES are served - not the rest of this folder - and only
on 127.0.0.1.
"""

import argparse
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import file_access_collector as collector

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECT_INTERVAL_SECONDS = 5

# URL path -> (file in this folder, content type)
ROUTES = {
    "/": ("test-raporu-defteri.html", "text/html; charset=utf-8"),
    "/index.html": ("test-raporu-defteri.html", "text/html; charset=utf-8"),
    "/recent_changes.json": ("turkak_recent_changes.json", "application/json; charset=utf-8"),
    "/file_access_live.json": ("file_access_live.json", "application/json; charset=utf-8"),
    "/file_access_recent.json": ("file_access_recent.json", "application/json; charset=utf-8"),
}


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = ROUTES.get(self.path.split("?", 1)[0])
        path = route and os.path.join(HERE, route[0])
        if not route or not os.path.isfile(path):
            self.send_error(404)
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", route[1])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # keep the console for collector output


def collect_forever():
    while True:
        try:
            collector.collect_once()
        except Exception as e:
            print(f"Collection failed: {e}")
            sys.stdout.flush()
        time.sleep(COLLECT_INTERVAL_SECONDS)


def main():
    parser = argparse.ArgumentParser(description="Serve the TÜRKAK dashboard locally with live file-access data.")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    threading.Thread(target=collect_forever, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    print(f"Dashboard: http://127.0.0.1:{args.port}/  (collecting every {COLLECT_INTERVAL_SECONDS}s, Ctrl+C to stop)")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
