import base64, os, select, socket, urllib.request, urllib.error, http.server, urllib.parse

PASSWORD = os.environ['PASSWORD']
TARGET = os.environ.get('PROXY_TARGET', 'http://hermes-agent-v2:8080')
PORT = int(os.environ.get('PORT', 8080))

# Hop-by-hop headers stripped from the forwarded WS handshake — they are
# rebuilt below so the upstream sees a clean, valid upgrade request.
_HOP_BY_HOP = frozenset({
    'connection', 'proxy-connection', 'upgrade', 'keep-alive',
    'transfer-encoding', 'host', 'authorization', 'content-length',
})

class Proxy(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def check_auth(self):
        auth = self.headers.get('Authorization', '')
        expected = base64.b64encode(f'admin:{PASSWORD}'.encode()).decode()
        return auth == f'Basic {expected}'

    def require_auth(self):
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Hermes"')
        # protocol_version=HTTP/1.1 keeps the connection alive — without an
        # explicit length the client can't tell where the 401 ends and hangs.
        self.send_header('Content-Length', '0')
        self.end_headers()

    def proxy_request(self):
        try:
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len) if content_len else None
            req_headers = {}
            for k, v in self.headers.items():
                kl = k.lower()
                if kl not in ('host', 'authorization', 'content-length'):
                    req_headers[k] = v
            req = urllib.request.Request(
                TARGET + self.path, data=body, headers=req_headers, method=self.command
            )
            resp = urllib.request.urlopen(req)
            body = resp.read()
            self.send_response(resp.status)
            for k, v in resp.headers.items():
                if k.lower() not in ('transfer-encoding', 'connection'):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except urllib.error.HTTPError as e:
            body = e.read()
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in ('transfer-encoding', 'connection'):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = str(e).encode()
            self.send_response(502)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def proxy_websocket(self):
        """Tunnel a WebSocket upgrade through to the upstream.

        The stdlib HTTP client can't speak the upgrade protocol, so the
        handshake and the byte stream are forwarded at the socket level.
        Runs inside a thread (ThreadingHTTPServer) — the tunnel is a long
        lived duplex connection.
        """
        target = urllib.parse.urlparse(TARGET)
        host = target.hostname
        port = target.port or 80
        upstream = None
        try:
            upstream = socket.create_connection((host, port), timeout=10)

            # Rebuild the handshake: forward the client's headers minus the
            # hop-by-hop set, then pin our own Connection/Upgrade.
            path = self.path or '/'
            req = f"GET {path} HTTP/1.1\r\n"
            for k, v in self.headers.items():
                if k.lower() not in _HOP_BY_HOP:
                    req += f"{k}: {v}\r\n"
            req += f"Host: {host}:{port}\r\n"
            req += "Connection: Upgrade\r\nUpgrade: websocket\r\n\r\n"
            upstream.sendall(req.encode('iso-8859-1'))

            # Read the upstream's response head and replay it verbatim.
            resp = b''
            while b'\r\n\r\n' not in resp:
                chunk = upstream.recv(4096)
                if not chunk:
                    break
                resp += chunk
            self.connection.sendall(resp)

            status_line = resp.split(b'\r\n', 1)[0]
            if b' 101 ' not in status_line:
                return  # handshake rejected — response already relayed

            # Anything the client already pipelined into the buffered reader
            # must reach the upstream before the select loop takes over.
            try:
                buffered = self.rfile.read1()
                if buffered:
                    upstream.sendall(buffered)
            except Exception:
                pass

            # Duplex relay until either side hangs up.
            client = self.connection
            sockets = [client, upstream]
            while True:
                readable, _, _ = select.select(sockets, [], [])
                for s in readable:
                    data = s.recv(65536)
                    if not data:
                        return
                    (upstream if s is client else client).sendall(data)
        except Exception:
            pass
        finally:
            if upstream:
                upstream.close()

    def do_GET(self):
        if not self.check_auth():
            return self.require_auth()
        if self.headers.get('Upgrade', '').lower() == 'websocket':
            return self.proxy_websocket()
        self.proxy_request()

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_GET

if __name__ == '__main__':
    httpd = http.server.ThreadingHTTPServer(('0.0.0.0', PORT), Proxy)
    print(f'Auth proxy listening on :{PORT}', flush=True)
    httpd.serve_forever()
