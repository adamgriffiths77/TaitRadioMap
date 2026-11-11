"""Serve the TAIT map and read explicitly configured KML files. Python stdlib only."""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import secrets
import socket
import ipaddress
from tile_cache import TileCache
from pdf_maps import PdfMaps
from urllib.parse import urlsplit, parse_qs
import xml.etree.ElementTree as ET
from radio_control import RadioController

ROOT = Path(__file__).resolve().parent
NS = '{http://www.opengis.net/kml/2.2}'


def read_positions(path):
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError('KML exceeds the 50 MB file limit')
    root = ET.fromstring(path.read_bytes())
    points = []
    def visit(node, session):
        if node.tag == NS + 'Placemark':
            point = node.find(NS + 'Point')
            if point is None:
                return
            coordinates = point.findtext(NS + 'coordinates', '').strip().split(',')
            when = node.findtext(NS + 'TimeStamp/' + NS + 'when', '')
            if len(coordinates) < 2 or not when:
                return
            try:
                lon, lat = map(float, coordinates[:2])
                timestamp = datetime.fromisoformat(when.replace('Z', '+00:00'))
                if timestamp.tzinfo is None or not all(map(math.isfinite, (lon, lat))) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    return
            except (ValueError, OverflowError):
                return
            name = node.findtext(NS + 'name', '').strip()
            description = node.findtext(NS + 'description', '')
            identity = re.search(r'(?:Radio ID suffix:|Caller ID:)\s*(\d+)', description)
            radio_id = name if re.fullmatch(r'\d+', name) else identity.group(1) if identity else 'Unknown radio'
            points.append({'id': radio_id, 'lat': lat, 'lon': lon,
                           'time': timestamp.astimezone(timezone.utc).isoformat(),
                           'session': f'{path.name}:{session}', 'description': description})
            return
        for index, child in enumerate(node):
            visit(child, f'{session}/{index}' if child.tag == NS + 'Folder' else session)
    visit(root, 'root')
    return points


SITE_ORIGIN = 'https://tait-radio-map-adam.docile-root-7865.chatgpt.site'


def collect_positions(files, optional_files=(), controller=None):
    points, errors, sources = [], [], []
    required = set(files)
    optional = set(optional_files) - required
    watched = list(dict.fromkeys([*files, *optional_files, *(controller.files() if controller else [])]))
    for file in watched:
        try:
            positions = read_positions(file)
            points.extend(positions)
            sources.append({'name': file.name, 'points': len(positions)})
        except FileNotFoundError as exc:
            if file not in optional:
                errors.append(f'{file.name}: {exc}')
        except (OSError, ValueError, ET.ParseError) as exc:
            errors.append(f'{file.name}: {exc}')
    return {'points': points, 'sources': sources, 'errors': errors,
            'updated': datetime.now(timezone.utc).isoformat()}


def make_handler(files, controller=None, token=None, optional_files=(), tile_cache=None, pdf_maps=None):
    token = token or secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def handle(self):
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # Tabs cancel requests on pan/zoom, navigation and reload. Once
                # disconnected there is no response to send and nothing to retry.
                self.close_connection = True

        def origin_allowed(self):
            allowed = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}', SITE_ORIGIN}
            allowed.add('http://' + self.headers.get('Host', ''))
            return not self.headers.get('Origin') or self.headers['Origin'] in allowed

        def send_json(self, payload, status=200):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            origin = self.headers.get('Origin')
            if origin and self.origin_allowed():
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Vary', 'Origin')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            return self.origin_allowed() and secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)

        def valid_host(self):
            host = self.headers.get('Host', '')
            port = self.server.server_port
            allowed = getattr(self.server, 'allowed_hosts', {'127.0.0.1', 'localhost'})
            if host in {f'{address}:{port}' for address in allowed}:
                return True
            # A LAN connection identifies the local interface even without DNS.
            return host == f'{self.connection.getsockname()[0]}:{port}'

        def do_OPTIONS(self):
            if not self.valid_host() or not self.origin_allowed():
                self.send_error(403)
                return
            self.send_response(204)
            if self.headers.get('Origin'):
                self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
            self.send_header('Access-Control-Allow-Private-Network', 'true')
            self.send_header('Vary', 'Origin')
            self.end_headers()

        def do_POST(self):
            if not self.valid_host() or not self.authorized():
                self.send_json({'error': 'Companion key or origin is invalid'}, 403)
                return
            try:
                route = urlsplit(self.path).path
                if route == '/api/maps/import' and pdf_maps:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 1 <= length <= 50*1024*1024 or self.headers.get_content_type() != 'application/pdf':
                        raise ValueError('Expected a PDF no larger than 50 MB')
                    query = parse_qs(urlsplit(self.path).query)
                    self.send_json(pdf_maps.import_pdf(self.rfile.read(length), query.get('name',['Map.pdf'])[0], int(query.get('page',['1'])[0]), int(query.get('viewport',['1'])[0])))
                    return
                length = int(self.headers.get('Content-Length', '0'))
                if length < 1 or length > 32768 or self.headers.get_content_type() != 'application/json':
                    raise ValueError('Expected a small JSON request')
                data = json.loads(self.rfile.read(length))
                route = urlsplit(self.path).path
                if route == '/api/maps/remove' and pdf_maps:
                    self.send_json(pdf_maps.remove(data.get('id', '')))
                    return
                if route == '/api/cache' and tile_cache:
                    self.send_json(tile_cache.configure(data))
                    return
                if controller is None:
                    raise ValueError('Radio controller is unavailable')
                if route == '/api/radio/start':
                    self.send_json(controller.start(data))
                elif route == '/api/radio/stop':
                    self.send_json(controller.stop())
                elif route == '/api/radio/poll':
                    if not isinstance(data, dict):
                        raise ValueError('Expected a radio ID')
                    self.send_json(controller.request_poll(data.get('id')))
                else:
                    self.send_json({'error': 'Unknown command'}, 404)
            except (OSError, ValueError, TypeError) as exc:
                self.send_json({'error': str(exc)}, 400)

        def do_GET(self):
            if not self.valid_host():
                self.send_error(403)
                return
            route = urlsplit(self.path).path
            if route.startswith('/tiles/') and tile_cache:
                try:
                    match = re.fullmatch(r'/tiles/(standard|humanitarian|topographic)/(\d+)/(\d+)/(\d+)\.png', route)
                    if not match: raise ValueError('Invalid tile path')
                    body = tile_cache.get(match[1], *map(int, match.group(2,3,4)), self.headers.get('Referer', ''))
                except (OSError, ValueError):
                    self.send_error(503, 'Tile unavailable and not cached')
                    return
                # A failed socket write is not a failed tile download. Let
                # handle() discard disconnects without trying a second response.
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers(); self.wfile.write(body)
                return
            if route == '/api/viewer/maps' and pdf_maps:
                if not self.origin_allowed():
                    self.send_json({'error':'Origin is invalid'},403)
                else: self.send_json({'maps':pdf_maps.catalog()})
                return
            if route.startswith('/maps/') and pdf_maps:
                try:
                    match = re.fullmatch(r'/maps/([a-f0-9]{32})\.png', route)
                    if not match: raise ValueError('Invalid map path')
                    body = pdf_maps.image(match[1])
                    self.send_response(200); self.send_header('Content-Type','image/png')
                    self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','private, max-age=86400')
                    self.end_headers(); self.wfile.write(body)
                except (OSError,ValueError): self.send_error(404)
                return
            if route == '/api/bootstrap':
                origin = self.headers.get('Origin')
                same_origin = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
                if self.client_address[0] not in ('127.0.0.1', '::1') or (origin and origin not in same_origin) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                    self.send_json({'error': 'Open the local viewer to obtain a companion key'}, 403)
                else:
                    self.send_json({'token': token})
                return
            if route == '/api/viewer/positions':
                # Read-only LAN feed; control endpoints still require the key.
                origin = self.headers.get('Origin')
                if (origin and origin != 'http://' + self.headers.get('Host', '')) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                    self.send_json({'error': 'Open the network viewer directly'}, 403)
                    return
                self.send_json(collect_positions(files, optional_files, controller))
                return
            if route.startswith('/api/') and not self.authorized():
                self.send_json({'error': 'Pair with the local companion first'}, 403)
                return
            if route == '/api/cache' and tile_cache:
                self.send_json(tile_cache.status())
                return
            if route == '/api/radio/status':
                self.send_json(controller.status() if controller else {'running': False, 'logs': []})
                return
            if route == '/api/radio/ports':
                try:
                    self.send_json({'ports': controller.port_provider() if controller else []})
                except (OSError, ValueError) as exc:
                    self.send_json({'error': str(exc)}, 400)
                return
            if route == '/api/positions':
                self.send_json(collect_positions(files, optional_files, controller))
                return
            else:
                assets = {'/': ('index.html', 'text/html'), '/index.html': ('index.html', 'text/html'),
                          '/app.mjs': ('app.mjs', 'text/javascript'), '/core.mjs': ('core.mjs', 'text/javascript'),
                          '/radio-ui.mjs': ('radio-ui.mjs', 'text/javascript'), '/maps.mjs': ('maps.mjs', 'text/javascript'),
                          '/radio.css': ('radio.css', 'text/css'),
                          '/leaflet.js': ('leaflet.js', 'text/javascript'), '/leaflet.css': ('leaflet.css', 'text/css'),
                          '/style.css': ('style.css', 'text/css')}
                if route not in assets:
                    self.send_error(404)
                    return
                filename, content_type = assets[route]
                body = (ROOT / 'dist' / filename).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kml', type=Path, nargs='+', help='KML files to watch (paths relative to your current directory)')
    parser.add_argument('--host', default='0.0.0.0', help='Listener address; default all network interfaces, use 127.0.0.1 for local only')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    files = [p.resolve() for p in args.kml] if args.kml else []
    optional_files = [] if args.kml else [ROOT.parent / 'polled_locations.kml', ROOT.parent / 'trip2.kml']
    controller = RadioController()
    token = secrets.token_urlsafe(32)
    cache = TileCache(ROOT / 'runtime' / 'map-cache.sqlite')
    with ThreadingHTTPServer((args.host, args.port), make_handler(files, controller, token, optional_files, cache, PdfMaps(ROOT / 'runtime' / 'pdf-maps'))) as server:
        addresses = {'127.0.0.1', 'localhost'}
        if args.host == '0.0.0.0':
            try:
                addresses.update(socket.gethostbyname_ex(socket.gethostname())[2])
            except socket.gaierror:
                print('Could not discover a network viewer address. For LAN access, use this computer\'s IPv4 address.', flush=True)
        else:
            addresses.add(args.host)
        server.allowed_hosts = addresses
        for address in sorted(addresses - {'127.0.0.1', 'localhost'}):
            print(f'Network viewer: http://{address}:{args.port}', flush=True)
        print(f'TAIT Radio Map: http://127.0.0.1:{args.port}', flush=True)
        print('Watching required files: ' + (', '.join(str(p) for p in files) or 'none'), flush=True)
        print('Optional legacy files (loaded when present): ' + (', '.join(str(p) for p in optional_files) or 'none'), flush=True)
        print('Private website companion key: ' + token, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            controller.stop()


if __name__ == '__main__':
    main()
