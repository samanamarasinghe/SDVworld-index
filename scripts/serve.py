#!/usr/bin/env python3
"""Static server for the repo root, plus a POST sink so browser harnesses can write
their results straight to disk.

The oracle and the benchmark both produce more data than a browser-automation
return value can carry, and neither should depend on a download directory. They
POST to /__sink/<relative-path> instead and this writes the body there.

    python3 scripts/serve.py [--port 8765] [--quiet]

Writes are confined to SINK_ROOTS. Bound to 127.0.0.1 only; this is a test
fixture, not a deployment.
"""
import argparse, functools, http.server, json, os, pathlib, socketserver, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SINK_ROOTS = ('docs/perf/', 'tests/')


class Handler(http.server.SimpleHTTPRequestHandler):
    quiet = False

    def do_POST(self):
        if not self.path.startswith('/__sink/'):
            self.send_error(404, 'no such endpoint')
            return
        rel = self.path[len('/__sink/'):]
        try:
            dest = self._resolve(rel)
        except ValueError as e:
            self.send_error(403, str(e))
            return
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        if not self.quiet:
            sys.stderr.write(f'sink: {len(body):,} B -> {dest.relative_to(ROOT)}\n')
        payload = json.dumps({'ok': True, 'path': str(dest.relative_to(ROOT)),
                              'bytes': len(body)}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    @staticmethod
    def _resolve(rel):
        """Confine sink writes, including anything ../ could reach, to SINK_ROOTS."""
        dest = (ROOT / rel).resolve()
        try:
            inside = dest.relative_to(ROOT).as_posix()
        except ValueError:
            raise ValueError('sink path escapes the repo')
        if not any(inside.startswith(p) for p in SINK_ROOTS):
            raise ValueError(f'sink path must live under one of {SINK_ROOTS}')
        return dest

    def send_head(self):
        """Refuse conditional requests outright.

        Cache-Control: no-store is not enough on its own. SimpleHTTPRequestHandler
        still sends Last-Modified, and Chrome will still revalidate with
        If-Modified-Since and happily reuse its cached copy on the 304 that comes
        back. That silently ran an OLD version of a harness here for two full
        twenty-five-minute runs, and the results looked like product failures.
        Dropping the conditional headers makes a 304 impossible, so a harness always
        gets the bytes on disk.
        """
        for h in ('If-Modified-Since', 'If-None-Match', 'If-Range'):
            while h in self.headers:
                del self.headers[h]
        return super().send_head()

    def end_headers(self):
        # Harness runs must never measure a stale artifact.
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, fmt, *args):
        if not self.quiet:
            super().log_message(fmt, *args)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    Handler.quiet = a.quiet
    handler = functools.partial(Handler, directory=str(ROOT))
    with Server(('127.0.0.1', a.port), handler) as httpd:
        sys.stderr.write(f'serving {ROOT} at http://127.0.0.1:{a.port}/\n')
        sys.stderr.flush()
        httpd.serve_forever()


if __name__ == '__main__':
    main()
