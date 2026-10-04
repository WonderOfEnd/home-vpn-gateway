#!/usr/bin/env python3
"""Tiny LAN-only web UI to add/remove domains that should bypass the VPN
tunnel (routed 'direct' instead of 'proxy'). Protected by HTTP Basic Auth."""
import base64
import json
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

EXCEPTIONS = "/etc/xray-exceptions.json"
PASSWORD_FILE = "/etc/xray-exceptions.password"
PORT = 8090

DOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$")


def load_domains():
    try:
        with open(EXCEPTIONS) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def save_and_apply(domains):
    with open(EXCEPTIONS, "w") as f:
        json.dump(sorted(set(domains)), f, indent=2)
    subprocess.run(["sudo", "/usr/local/bin/apply-xray-exceptions.py"], check=True)


def check_auth(header):
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode()
        _, password = decoded.split(":", 1)
    except Exception:
        return False
    with open(PASSWORD_FILE) as f:
        expected = f.read().strip()
    return password == expected


PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Исключения VPN</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 480px; margin: 2rem auto; padding: 0 1rem; background:#fafafa; }}
h1 {{ font-size: 1.3rem; }}
form.add {{ display: flex; gap: .5rem; margin: 1rem 0; }}
input[type=text] {{ flex: 1; padding: .6rem; font-size: 1rem; border: 1px solid #ccc; border-radius: 6px; }}
button {{ padding: .6rem 1rem; font-size: 1rem; border: 0; border-radius: 6px; background: #222; color: #fff; }}
li {{ display: flex; justify-content: space-between; align-items: center; background: #fff; padding: .6rem .8rem; margin: .4rem 0; border-radius: 6px; border: 1px solid #e0e0e0; }}
li button {{ background: #c0392b; padding: .3rem .7rem; font-size: .85rem; }}
ul {{ list-style: none; padding: 0; }}
.empty {{ color: #888; font-size: .9rem; }}
.hint {{ color: #888; font-size: .8rem; margin-top: 1.5rem; }}
</style></head>
<body>
<h1>Исключения из VPN-туннеля</h1>
<p class="hint">Сайты из списка идут напрямую, в обход прокси.</p>
<form class="add" method="post" action="/add">
  <input type="text" name="domain" placeholder="example.com" required pattern="[a-zA-Z0-9.-]+">
  <button type="submit">Добавить</button>
</form>
<ul>
{items}
</ul>
</body></html>
"""

ITEM = """<li>{domain}
  <form method="post" action="/remove" style="margin:0">
    <input type="hidden" name="domain" value="{domain}">
    <button type="submit">Убрать</button>
  </form>
</li>"""


class Handler(BaseHTTPRequestHandler):
    def _unauthorized(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="exceptions"')
        self.end_headers()

    def _render(self):
        domains = load_domains()
        items = "".join(ITEM.format(domain=d) for d in domains) or '<p class="empty">Пока пусто</p>'
        body = PAGE.format(items=items).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not check_auth(self.headers.get("Authorization")):
            return self._unauthorized()
        if self.path == "/":
            return self._render()
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if not check_auth(self.headers.get("Authorization")):
            return self._unauthorized()
        length = int(self.headers.get("Content-Length", 0))
        data = parse_qs(self.rfile.read(length).decode())
        domain = data.get("domain", [""])[0].strip().lower()

        if self.path == "/add" and DOMAIN_RE.match(domain):
            domains = load_domains()
            domains.append(domain)
            save_and_apply(domains)
        elif self.path == "/remove":
            domains = [d for d in load_domains() if d != domain]
            save_and_apply(domains)

        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"listening on :{PORT}")
    server.serve_forever()
