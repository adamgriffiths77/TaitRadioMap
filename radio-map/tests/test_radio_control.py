import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import threading
sys.path.insert(0, str(Path(__file__).parents[1]))
from radio_control import RadioController, validate_settings
from serve import make_handler, SITE_ORIGIN

PORTS = [{'device':'COM7', 'description':'Test adapter'}]
SETTINGS = {'port':'COM7', 'baud':9600, 'mode':'listen', 'flow':'none'}


class FakeProcess:
    def __init__(self):
        self.stdout = io.StringIO('INFO: simulated radio ready\n')
        self.code = None
    def poll(self):
        return self.code
    def terminate(self):
        self.code = 0
    def wait(self, timeout):
        return self.code


class RadioTests(unittest.TestCase):
    def test_http_controls_require_key_and_allowlisted_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = RadioController(folder, lambda:PORTS, lambda *a, **k:FakeProcess())
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler([], manager, 'test-key'))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            def request(method, path, data=None, headers=None):
                connection = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                connection.request(method, path, json.dumps(data) if data is not None else None, headers or {})
                response = connection.getresponse()
                status, body, cors = response.status, response.read(), response.getheader('Access-Control-Allow-Origin')
                connection.close()
                return status, json.loads(body) if body else None, cors
            try:
                self.assertEqual(request('GET','/api/bootstrap')[1]['token'], 'test-key')
                self.assertEqual(request('GET','/api/bootstrap',headers={'Origin':SITE_ORIGIN})[0],403)
                self.assertEqual(request('GET','/api/radio/status')[0],403)
                auth={'Authorization':'Bearer test-key','Origin':SITE_ORIGIN,'Content-Type':'application/json'}
                self.assertEqual(request('GET','/api/radio/ports',headers=auth)[1]['ports'],PORTS)
                self.assertEqual(request('GET','/api/radio/status',headers={**auth,'Origin':'https://untrusted.example'})[0],403)
                self.assertEqual(request('POST','/api/radio/start',SETTINGS,auth)[1]['running'],True)
                self.assertEqual(request('POST','/api/radio/start',SETTINGS,auth)[0],400)
                self.assertEqual(request('POST','/api/radio/stop',{},auth)[1]['running'],False)
                self.assertEqual(request('OPTIONS','/api/radio/start',headers={'Origin':SITE_ORIGIN})[2],SITE_ORIGIN)
                self.assertEqual(request('GET','/api/positions',headers=auth)[0],200)
            finally:
                manager.stop(); server.shutdown(); server.server_close(); thread.join()

    def test_invalid_settings(self):
        for change in [{'port':'COM9'}, {'baud':1}, {'mode':'shell'}, {'flow':'bad'},
                       {'mode':'poll','radios':[]},
                       {'mode':'poll','radios':[{'id':'3000030','interval':0}]},
                       {'mode':'poll','radios':[{'id':'3000030','interval':60},{'id':'4000030','interval':60}]}]:
            with self.assertRaises(ValueError): validate_settings({**SETTINGS, **change}, PORTS)

    def test_start_stop_and_poll_command(self):
        commands = []
        def launch(command, **kwargs):
            commands.append(command)
            return FakeProcess()
        with tempfile.TemporaryDirectory() as folder:
            manager = RadioController(folder, lambda:PORTS, launch)
            self.assertFalse(manager.status()['running'])
            manager.start(SETTINGS)
            self.assertTrue(manager.status()['running'])
            self.assertIn('tait_to_kml.py', commands[0][2])
            with self.assertRaises(ValueError): manager.start(SETTINGS)
            manager.stop()
            self.assertFalse(manager.status()['running'])
            manager.start({**SETTINGS,'mode':'poll','radios':[{'id':'3000030','interval':60}]})
            command = commands[1]
            self.assertIn('tait_poll_to_kml.py', command[2])
            config = Path(command[command.index('--config')+1])
            self.assertEqual(json.loads(config.read_text())['radios'][0]['id'], '3000030')
            self.assertNotEqual(commands[0][commands[0].index('--output')+1], command[command.index('--output')+1])
            manager.stop()
