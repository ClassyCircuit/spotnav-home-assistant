"""Local-only test server for the actual bundled panel and preview fixture."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        if path.startswith('/spotnav-sidebar/'):
            return str(ROOT / 'custom_components' / 'spotnav' / 'www' / 'sidebar' / path.split('/')[-1].split('?')[0])
        if path.split('?')[0] == '/spotnav-card.js':
            return str(ROOT / 'custom_components' / 'spotnav' / 'www' / 'spotnav-card.js')
        return super().translate_path(path)

if __name__ == '__main__':
    import os
    os.chdir(ROOT / 'frontend')
    ThreadingHTTPServer(('127.0.0.1', int(os.environ.get('SPOTNAV_HTTP_PORT', '8766'))), Handler).serve_forever()
