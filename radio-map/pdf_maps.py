"""Import ISO geospatial PDF viewports into bounded Web Mercator overlays."""
import io
import json
import math
from pathlib import Path
import re
import threading
import uuid

class PdfMaps:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.Lock()

    def catalog(self):
        if not self.root.exists(): return []
        result = []
        for path in sorted(self.root.glob('*.json')):
            try:
                item = json.loads(path.read_text(encoding='utf-8'))
                if (self.root / (item['id'] + '.png')).is_file(): result.append(item)
            except (OSError, ValueError, KeyError): pass
        return result

    def image(self, identity):
        if not re.fullmatch(r'[a-f0-9]{32}', identity): raise ValueError('Invalid map ID')
        return (self.root / (identity + '.png')).read_bytes()

    def remove(self, identity):
        if not re.fullmatch(r'[a-f0-9]{32}', identity): raise ValueError('Invalid map ID')
        with self.lock:
            for suffix in ('.json', '.png'):
                (self.root / (identity + suffix)).unlink(missing_ok=True)
        return {'maps': self.catalog()}

    def import_pdf(self, content, name, page_number=1, viewport_number=1):
        try:
            import numpy as np
            from PIL import Image, ImageDraw
            from pypdf import PdfReader
            import pypdfium2 as pdfium
            from pyproj import CRS, Transformer
        except ImportError as exc:
            raise ValueError('Install PDF map support: python -m pip install -r radio-map/requirements-maps.txt') from exc
        if not content.startswith(b'%PDF-') or len(content) > 50*1024*1024:
            raise ValueError('Choose a PDF no larger than 50 MB')
        with self.lock:
            try:
                reader = PdfReader(io.BytesIO(content))
                if reader.is_encrypted: raise ValueError('Encrypted PDF maps are not supported')
                if not 1 <= page_number <= len(reader.pages): raise ValueError('Page number is outside this PDF')
                page = reader.pages[page_number-1]
                if page.rotation % 360: raise ValueError('Rotated PDF pages are not supported. Export an unrotated geospatial PDF.')
                viewports = page.get('/VP', [])
                if hasattr(viewports, 'get_object'): viewports = viewports.get_object()
                if not isinstance(viewports, list): viewports = [viewports]
                if not 1 <= viewport_number <= len(viewports):
                    raise ValueError('No matching ISO geospatial viewport. Plain PDFs and legacy LGIDict GeoPDF files are not supported; export an ISO geospatial PDF from GIS software.')
                vp = viewports[viewport_number-1].get_object()
                measure = vp.get('/Measure', {}).get_object() if hasattr(vp.get('/Measure', {}), 'get_object') else vp.get('/Measure', {})
                if measure.get('/Subtype') != '/GEO': raise ValueError('Selected viewport is not geospatial')
                gcs = measure.get('/GCS', {}).get_object() if hasattr(measure.get('/GCS', {}), 'get_object') else measure.get('/GCS', {})
                if gcs.get('/WKT'): crs = CRS.from_wkt(str(gcs['/WKT']))
                elif gcs.get('/EPSG'): crs = CRS.from_epsg(int(gcs['/EPSG']))
                else: raise ValueError('Map has no supported CRS definition (WKT or EPSG)')
                if not (crs.is_projected or crs.is_geographic): raise ValueError('Unsupported map coordinate system')
                points = np.asarray(measure.get('/GPTS', []), dtype=float).reshape(-1,2)
                local = np.asarray(measure.get('/LPTS', []), dtype=float).reshape(-1,2)
                if len(points) != len(local) or len(points)<3 or len(points)>100:
                    raise ValueError('Map needs matching GPTS/LPTS control points')
                if not np.isfinite(points).all() or not np.isfinite(local).all() or (abs(points[:,0])>85).any() or (abs(points[:,1])>180).any():
                    raise ValueError('Map control points are outside supported geographic limits')
                if np.ptp(points[:,1])>180: raise ValueError('Maps crossing the date line are not supported')
                geographic = crs.geodetic_crs
                project = Transformer.from_crs(geographic, crs, always_xy=True)
                x,y = project.transform(points[:,1],points[:,0])
                target = np.column_stack((x,y))
                design = np.column_stack((local,np.ones(len(local))))
                affine, _, rank, _ = np.linalg.lstsq(design,target,rcond=None)
                if rank<3: raise ValueError('Map control points are collinear')
                tolerance = max(1e-7 if crs.is_geographic else 0.5, float(np.ptp(target,axis=0).max()) * .0001)
                if np.max(np.linalg.norm(design@affine-target,axis=1))>tolerance:
                    raise ValueError('Map control points do not fit a consistent affine georeference')
                inverse = np.linalg.inv(affine[:2,:])
                bbox = list(map(float,vp['/BBox']))
                if len(bbox) != 4 or not all(math.isfinite(v) for v in bbox): raise ValueError('Invalid map viewport bounds')
                x0,y0,x1,y1 = bbox
                dx,dy = x1-x0,y1-y0
                if not dx or not dy: raise ValueError('Invalid map viewport bounds: zero-sized frame')
                # Keep the signed frame: some exporters define LPTS from the top
                # down. Sorting BBox alone would silently flip their georeference.
                media = list(map(float,page.mediabox)); cropbox = list(map(float,page.cropbox))
                cb = [max(media[0],cropbox[0]),max(media[1],cropbox[1]),min(media[2],cropbox[2]),min(media[3],cropbox[3])]
                left,bottom = max(min(x0,x1),cb[0]),max(min(y0,y1),cb[1])
                right,top = min(max(x0,x1),cb[2]),min(max(y0,y1),cb[3])
                if right<=left or top<=bottom: raise ValueError('Invalid map viewport bounds: frame does not intersect the visible page')
                boundary = np.asarray(measure.get('/Bounds',[0,0,0,1,1,1,1,0]),dtype=float).reshape(-1,2)
                if len(boundary)<3 or len(boundary)>100 or not np.isfinite(boundary).all() or (boundary<0).any() or (boundary>1).any(): raise ValueError('Unsupported map neatline')
                # Clip the neatline in the original unit-square coordinates.
                u0,u1 = sorted(((left-x0)/dx,(right-x0)/dx))
                v0,v1 = sorted(((bottom-y0)/dy,(top-y0)/dy))
                boundary = np.asarray(clip_polygon(boundary.tolist(),u0,v0,u1,v1))
                if len(boundary)<3: raise ValueError('Map neatline does not intersect the visible page')
                # Densify each edge before finding projected extent.
                edge = np.concatenate([a+(b-a)*np.linspace(0,1,33)[:,None] for a,b in zip(boundary,np.roll(boundary,-1,axis=0))])
                source_edge = np.column_stack((edge,np.ones(len(edge))))@affine
                to_web = Transformer.from_crs(crs,3857,always_xy=True)
                wx,wy = to_web.transform(source_edge[:,0],source_edge[:,1])
                west,east,south,north = min(wx),max(wx),min(wy),max(wy)
                if not all(math.isfinite(v) for v in (west,east,south,north)) or east<=west or north<=south: raise ValueError('Invalid projected map extent')
                # Bounded raster; rendering happens locally, with no PDF JavaScript execution.
                document = pdfium.PdfDocument(content)
                pdfpage = document[page_number-1]
                try:
                    scale = min(4,4096/max(right-left,top-bottom))
                    actual = pdfpage.get_bbox()
                    crop=(max(0,left-actual[0]),max(0,bottom-actual[1]),max(0,actual[2]-right),max(0,actual[3]-top))
                    bitmap=pdfpage.render(scale=scale,crop=crop,may_draw_forms=False)
                    try: image=bitmap.to_pil().convert('RGBA').copy()
                    finally: bitmap.close()
                finally:
                    pdfpage.close(); document.close()
                mask=Image.new('L',image.size)
                ImageDraw.Draw(mask).polygon([((x0+float(u)*dx-left)*image.width/(right-left),(top-y0-float(v)*dy)*image.height/(top-bottom)) for u,v in boundary],fill=255)
                image.putalpha(mask)
                pixels=np.asarray(image)
                aspect=(east-west)/(north-south)
                width=4096 if aspect>=1 else max(1,round(4096*aspect))
                height=max(1,round(4096/aspect)) if aspect>=1 else 4096
                out=np.zeros((height,width,4),dtype=np.uint8)
                from_web=Transformer.from_crs(3857,crs,always_xy=True)
                columns=west+(np.arange(width)+.5)*(east-west)/width
                for start in range(0,height,64):
                    stop=min(height,start+64)
                    rows=north-(np.arange(start,stop)+.5)*(north-south)/height
                    xx,yy=np.meshgrid(columns,rows)
                    sx,sy=from_web.transform(xx,yy)
                    uv=(np.stack((sx,sy),axis=-1)-affine[2])@inverse
                    px=(x0+uv[:,:,0]*dx-left)*image.width/(right-left)-.5
                    py=(top-y0-uv[:,:,1]*dy)*image.height/(top-bottom)-.5
                    finite=np.isfinite(px)&np.isfinite(py)
                    valid=finite&(px>=0)&(py>=0)&(px<image.width)&(py<image.height)
                    ix=np.clip(np.nan_to_num(px),0,image.width-1).astype(int)
                    iy=np.clip(np.nan_to_num(py),0,image.height-1).astype(int)
                    block=pixels[iy,ix].copy(); block[~valid]=0; out[start:stop]=block
                identity=uuid.uuid4().hex
                self.root.mkdir(parents=True,exist_ok=True)
                Image.fromarray(out).save(self.root/(identity+'.png'))
                lonlat=Transformer.from_crs(3857,4326,always_xy=True)
                w,s=lonlat.transform(west,south); e,n=lonlat.transform(east,north)
                metadata={'id':identity,'name':Path(name).name[:120] or 'PDF map','page':page_number,'viewport':viewport_number,
                          'bounds':[[s,w],[n,e]],'crs':crs.to_string(),'width':width,'height':height,
                          'bytes':(self.root/(identity+'.png')).stat().st_size}
                (self.root/(identity+'.json')).write_text(json.dumps(metadata),encoding='utf-8')
                return metadata
            except ValueError: raise
            except Exception as exc:
                raise ValueError('Cannot import this geospatial PDF: '+str(exc)[:240]) from exc


def clip_polygon(points, left, bottom, right, top):
    """Sutherland-Hodgman clipping without changing the frame orientation."""
    for axis, limit, keep_greater in ((0,left,True),(0,right,False),(1,bottom,True),(1,top,False)):
        output=[]
        if not points: break
        previous=points[-1]
        previous_inside=(previous[axis]>=limit) if keep_greater else (previous[axis]<=limit)
        for current in points:
            inside=(current[axis]>=limit) if keep_greater else (current[axis]<=limit)
            if inside != previous_inside:
                fraction=(limit-previous[axis])/(current[axis]-previous[axis])
                output.append([previous[i]+fraction*(current[i]-previous[i]) for i in (0,1)])
            if inside: output.append(current)
            previous,previous_inside=current,inside
        points=output
    return points
