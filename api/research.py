"""Vercel HTTP entrypoint; public allowlisted data only."""
from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
from hosted_reader import read


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        allowed = {'action', 'symbol', 'id'}
        action = query.get('action', ['stocks'])[0]
        status = 200
        try:
            if len(self.path)>2048 or not set(query).issubset(allowed) or any(len(v) != 1 for v in query.values()):
                raise ValueError('Invalid reader request.')
            body = read(action, query.get('symbol', [None])[0], query.get('id', [None])[0])
        except ValueError as error:
            status, body = 400, {'error': str(error)[:180]}
        except Exception as error:
            print('Public source unavailable:', action, type(error).__name__)
            status, body = 502, {'error': 'The public source is unavailable right now. Try again or open the company source.'}
        raw = json.dumps(body, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        # Quotes retain exchange timestamps; never serve stale responses on errors.
        ttl = 10 if action == 'quote' else 300
        self.send_header('Cache-Control', f'public, max-age=0, s-maxage={ttl}' if status == 200 else 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        self.send_error(405, 'This reader only accepts GET requests.')
