import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer
from serve import make_handler
class MapRoutes(unittest.TestCase):
 def test_import_key_required_and_lan_catalog_readable(self):
  class Maps:
   calls=[]
   def catalog(self):return [{'id':'a'*32,'name':'Test.pdf'}]
   def image(self,identity):return b'\x89PNGtest'
   def import_pdf(self,content,name,page,viewport):
    self.calls.append((content,name,page,viewport));return {'id':'a'*32}
  maps=Maps();server=ThreadingHTTPServer(('127.0.0.1',0),make_handler([],token='secret',pdf_maps=maps))
  worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
  def request(method,path,body=None,headers=None):
   client=http.client.HTTPConnection('127.0.0.1',server.server_port)
   client.request(method,path,body,headers or {});response=client.getresponse();result=(response.status,response.read());client.close();return result
  try:
   self.assertEqual(request('GET','/api/viewer/maps')[0],200)
   self.assertEqual(request('GET','/maps/'+('a'*32)+'.png')[1],b'\x89PNGtest')
   self.assertEqual(request('POST','/api/maps/import',b'%PDF-test',{'Content-Type':'application/pdf'})[0],403)
   result=request('POST','/api/maps/import?name=Test.pdf&page=2&viewport=3',b'%PDF-test',{'Content-Type':'application/pdf','Authorization':'Bearer secret'})
   self.assertEqual(result[0],200);self.assertEqual(maps.calls,[(b'%PDF-test','Test.pdf',2,3)])
   self.assertEqual(request('POST','/api/maps/remove','{}',{'Content-Type':'application/json'})[0],403)
  finally:server.shutdown();server.server_close();worker.join()
