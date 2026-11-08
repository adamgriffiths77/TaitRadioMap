import unittest
import threading
import http.client
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from serve import make_handler
class SharedViewerTests(unittest.TestCase):
 def test_multiple_readers_share_positions_without_control_access(self):
  class Controller:
   def files(self): return [Path(__file__).parent/'sample.kml']
  server=ThreadingHTTPServer(('127.0.0.1',0),make_handler([],Controller(),'private-key'))
  thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
  def request(path,headers=None,method='GET'):
   connection=http.client.HTTPConnection('127.0.0.1',server.server_port)
   connection.request(method,path,headers=headers or {})
   response=connection.getresponse(); result=(response.status,json.loads(response.read())); connection.close(); return result
  try:
   first=request('/api/viewer/positions'); second=request('/api/viewer/positions')
   self.assertEqual(first[0],200); self.assertTrue(first[1]['points'])
   self.assertEqual(first[1]['points'],second[1]['points'])
   self.assertNotIn('token',first[1])
   self.assertEqual(request('/api/radio/stop',method='POST')[0],403)
   self.assertEqual(request('/api/viewer/positions',{'Origin':'https://untrusted.example'})[0],403)
  finally:
   server.shutdown();server.server_close();thread.join()
