import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from http.server import BaseHTTPRequestHandler
from serve import make_handler

class DisconnectTests(unittest.TestCase):
 def test_expected_disconnects_are_quiet_but_programming_errors_are_not(self):
  handler=object.__new__(make_handler([]))
  for exception in (BrokenPipeError(),ConnectionResetError(),ConnectionAbortedError(10053,'aborted')):
   with patch.object(BaseHTTPRequestHandler,'handle',side_effect=exception):
    handler.handle();self.assertTrue(handler.close_connection)
  with patch.object(BaseHTTPRequestHandler,'handle',side_effect=RuntimeError('real fault')):
   with self.assertRaises(RuntimeError):handler.handle()
 def test_tile_write_failure_does_not_attempt_second_http_response(self):
  cache=SimpleNamespace(get=lambda *args:b'\x89PNGdata')
  handler=object.__new__(make_handler([],tile_cache=cache))
  handler.server=SimpleNamespace(server_port=8765)
  handler.headers={'Host':'127.0.0.1:8765'};handler.path='/tiles/standard/0/0/0.png'
  handler.send_response=Mock();handler.send_header=Mock();handler.end_headers=Mock();handler.send_error=Mock()
  handler.wfile=SimpleNamespace(write=Mock(side_effect=ConnectionAbortedError(10053,'aborted')))
  with self.assertRaises(ConnectionAbortedError):handler.do_GET()
  handler.send_response.assert_called_once_with(200);handler.send_error.assert_not_called()
