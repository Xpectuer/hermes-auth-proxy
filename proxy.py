import base64, os, http.server, urllib.request, urllib.error

PASSWORD = os.environ['PASSWORD']
TARGET = os.environ.get('PROXY_TARGET', 'http://hermes-agent-v2:8080')
PORT = int(os.environ.get('PORT', 8080))

class Proxy(http.server.BaseHTTPRequestHandler):
    def check_auth(self):
        auth = self.headers.get('Authorization', '')
        expected = base64.b64encode(f'admin:{PASSWORD}'.encode()).decode()
        return auth == f'Basic {expected}'

    def require_auth(self):
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Hermes"')
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
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def do_GET(self):
        if not self.check_auth():
            return self.require_auth()
        self.proxy_request()

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_GET

if __name__ == '__main__':
    httpd = http.server.HTTPServer(('0.0.0.0', PORT), Proxy)
    print(f'Auth proxy listening on :{PORT}', flush=True)
    httpd.serve_forever()
