"""Minimal OAuth callback; expose only through a trusted HTTPS reverse proxy."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse
from .spotify_account import AccountError


def start_callback(account, host='0.0.0.0', port=8080):
    """Start the OAuth callback HTTP server and return its lifecycle handle."""
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass  # Request URLs contain one-use authorization codes.

        def do_GET(self):
            status, message = 400, 'Invalid authorization request.'
            if len(self.path) > 8192 or urlparse(self.path).path != '/spotify/callback':
                status = 404
            else:
                try:
                    query = parse_qs(urlparse(self.path).query, max_num_fields=8)
                    if any(len(v) != 1 for v in query.values()):
                        raise AccountError('Invalid authorization request.')
                    account.complete(query.get('state', [''])[0], query.get('code', [None])[0], 'error' in query)
                    status, message = 200, 'Spotify connected. Return to Telegram and use /current. Spotify подключён. Вернитесь в Telegram: /current.'
                except AccountError as error:
                    message = str(error)
                except Exception:
                    status, message = 503, 'Authorization unavailable. Try a new link in the bot.'
            body = message.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    Thread(target=server.serve_forever, daemon=True).start()
    return server
