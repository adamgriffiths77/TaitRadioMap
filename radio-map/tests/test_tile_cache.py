import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from tile_cache import TileCache
class CacheTests(unittest.TestCase):
 def test_offline_limit_clear_and_persistence(self):
  with tempfile.TemporaryDirectory() as directory:
   cache=TileCache(Path(directory)/'tiles.sqlite')
   png=b'\x89PNG'+b'x'*100
   cache.db.execute('INSERT INTO tiles VALUES(?,?,?,?,?,?)',('standard/0/0/0',png,0,0,'','')); cache.db.commit()
   with patch('tile_cache.urlopen',side_effect=OSError('offline')):
    self.assertEqual(cache.get('standard',0,0,0),png)
    with self.assertRaises(OSError): cache.get('standard',1,0,0)
   cache.configure({'limit_mb':10})
   second=TileCache(Path(directory)/'tiles.sqlite')
   self.assertEqual(second.status()['tiles'],1); second.db.close()
   cache.configure({'clear':True})
   self.assertEqual(cache.status()['bytes'],0)
   with self.assertRaises(ValueError): cache.configure({'limit_mb':0})
   with self.assertRaises(ValueError): cache.get('standard',0,5,0)
   cache.db.close()
 def test_eviction(self):
  with tempfile.TemporaryDirectory() as directory:
   cache=TileCache(Path(directory)/'tiles.sqlite')
   for index in range(3): cache.db.execute('INSERT INTO tiles VALUES(?,?,?,?,?,?)',(str(index),b'x'*5*1024*1024,0,index,'',''))
   cache.db.commit(); cache.configure({'limit_mb':10})
   self.assertEqual(cache.status()['tiles'],2)
   self.assertIsNone(cache.db.execute('SELECT key FROM tiles WHERE key="0"').fetchone())
   cache.db.close()

class ConcurrentCacheTests(unittest.TestCase):
 def test_slow_download_does_not_block_cached_tiles_or_clear(self):
  import threading
  import time
  from concurrent.futures import ThreadPoolExecutor
  entered=threading.Event();release=threading.Event()
  png=b'\x89PNG'+b'x'*100
  class Response:
   code=200;headers={'Cache-Control':'max-age=600'}
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,*args):return png
  def download(*args,**kwargs):
   entered.set();release.wait(5);return Response()
  with tempfile.TemporaryDirectory() as directory:
   cache=TileCache(Path(directory)/'tiles.sqlite')
   cache.db.execute('INSERT INTO tiles VALUES(?,?,?,?,?,?)',('standard/0/0/0',png,time.time()+600,0,'',''));cache.db.commit()
   try:
    with patch('tile_cache.urlopen',side_effect=download),ThreadPoolExecutor(max_workers=3) as pool:
     pending=pool.submit(cache.get,'standard',1,0,0)
     try:
      self.assertTrue(entered.wait(2))
      self.assertEqual(pool.submit(cache.get,'standard',0,0,0).result(timeout=1),png)
      self.assertEqual(pool.submit(cache.configure,{'clear':True}).result(timeout=1)['tiles'],0)
     finally:release.set()
     self.assertEqual(pending.result(timeout=2),png)
     self.assertEqual(cache.status()['tiles'],0)
   finally:release.set();cache.db.close()
