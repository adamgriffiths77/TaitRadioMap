"""Bounded, persistent cache of interactively requested map tiles."""
import sqlite3
import threading
import time
import re
from urllib.request import Request, urlopen
from urllib.error import HTTPError

PROVIDERS = {
 'standard': 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
 'humanitarian': 'https://a.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png',
 'topographic': 'https://a.tile.opentopomap.org/{z}/{x}/{y}.png',
}
class TileCache:
 def __init__(self, path):
  path.parent.mkdir(parents=True, exist_ok=True)
  self.db = sqlite3.connect(path, check_same_thread=False)
  self.lock = threading.RLock()
  self.download_locks = [threading.Lock() for _ in range(32)]
  self.download_slots = threading.BoundedSemaphore(4)
  self.generation = 0
  self.db.executescript('CREATE TABLE IF NOT EXISTS tiles (key TEXT PRIMARY KEY, body BLOB, expires REAL, used REAL, etag TEXT, modified TEXT); CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, mb INTEGER); INSERT OR IGNORE INTO settings VALUES(1,250);')
  self.db.commit()
 def status(self):
  with self.lock:
   size,count = self.db.execute('SELECT coalesce(sum(length(body)),0),count(*) FROM tiles').fetchone()
   return dict(bytes=size, tiles=count, limit_mb=self.db.execute('SELECT mb FROM settings').fetchone()[0])
 def configure(self, data):
  with self.lock:
   if 'limit_mb' in data:
    value = data['limit_mb']
    if type(value) is not int or not 10 <= value <= 10000: raise ValueError('Cache limit must be 10–10000 MB')
    self.db.execute('UPDATE settings SET mb=?',(value,))
   if data.get('clear'):
    self.generation += 1
    self.db.execute('DELETE FROM tiles')
   self.trim(); self.db.commit()
   # Reclaim freed disk pages after explicit clear or limit reduction.
   self.db.execute('VACUUM')
   return self.status()
 def trim(self):
  limit=self.status()['limit_mb']*1024*1024
  while self.status()['bytes']>limit:
   self.db.execute('DELETE FROM tiles WHERE key=(SELECT key FROM tiles ORDER BY used LIMIT 1)')
 def _lookup(self, key):
  with self.lock:
   row=self.db.execute('SELECT body,expires,etag,modified FROM tiles WHERE key=?',(key,)).fetchone()
   if row:
    self.db.execute('UPDATE tiles SET used=? WHERE key=?',(time.time(),key)); self.db.commit()
   return row, self.generation

 def get(self, provider,z,x,y,referer=''):
  if provider not in PROVIDERS or not 0<=z<=19 or not 0<=x<2**z or not 0<=y<2**z: raise ValueError('Invalid tile')
  key=f'{provider}/{z}/{x}/{y}'
  row,_=self._lookup(key)
  if row and row[1]>time.time(): return row[0]
  # Short database transactions keep cached reads/settings responsive while
  # downloads wait for the network. Striped locks coalesce identical requests
  # without an ever-growing dictionary; at most four downloads run at once.
  with self.download_locks[hash(key)%len(self.download_locks)]:
   row,generation=self._lookup(key)
   if row and row[1]>time.time(): return row[0]
   headers={'User-Agent':'TaitRadioMap/1.0 (+https://tait-radio-map-adam.docile-root-7865.chatgpt.site/)'}
   if referer: headers['Referer']=referer
   if row and row[2]: headers['If-None-Match']=row[2]
   if row and row[3]: headers['If-Modified-Since']=row[3]
   try:
    with self.download_slots:
     try:
      response=urlopen(Request(PROVIDERS[provider].format(z=z,x=x,y=y),headers=headers),timeout=4)
     except HTTPError as exc:
      if exc.code!=304 or not row: raise
      response=exc
     with response:
      body=row[0] if response.code==304 else response.read(1024*1024+1)
      if len(body)>1024*1024 or not body.startswith(b'\x89PNG'): raise ValueError('Invalid map tile response')
      cache=response.headers.get('Cache-Control','')
      match=re.search(r'max-age=(\d+)',cache)
      ttl=int(match[1]) if match else 7*86400
      etag=response.headers.get('ETag',row[2] if row else '')
      modified=response.headers.get('Last-Modified',row[3] if row else '')
    if 'no-store' not in cache:
     with self.lock:
      # Clear cache also invalidates downloads already in progress.
      if generation==self.generation:
       now=time.time()
       self.db.execute('INSERT OR REPLACE INTO tiles VALUES(?,?,?,?,?,?)',(key,body,now+ttl,now,etag,modified))
       self.trim(); self.db.commit()
    return body
   except (OSError,ValueError):
    if row: return row[0]
    raise
