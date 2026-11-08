import io
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, ArrayObject, FloatObject, NumberObject, DecodedStreamObject
from pdf_maps import PdfMaps

def array(values): return ArrayObject([FloatObject(v) for v in values])
def synthetic_pdf(geospatial=True, projected=False):
    writer=PdfWriter();page=writer.add_blank_page(width=600,height=600)
    stream=DecodedStreamObject();stream.set_data(b'0.9 0.95 0.85 rg 50 50 500 500 re f 0 0.5 0 RG 3 w 50 50 500 500 re S 50 50 m 550 550 l S 550 50 m 50 550 l S')
    page[NameObject('/Contents')]=writer._add_object(stream)
    if geospatial:
        latlon=[-38,145,-37.9,145,-37.9,145.1,-38,145.1]
        crs=4326
        if projected:
            from pyproj import Transformer
            inverse=Transformer.from_crs(32755,4326,always_xy=True)
            latlon=[]
            for x,y in [(300000,5790000),(300000,5800000),(310000,5800000),(310000,5790000)]:
                lon,lat=inverse.transform(x,y);latlon.extend([lat,lon])
            crs=32755
        measure=DictionaryObject({NameObject('/Type'):NameObject('/Measure'),NameObject('/Subtype'):NameObject('/GEO'),NameObject('/GPTS'):array(latlon),NameObject('/LPTS'):array([0,0,0,1,1,1,1,0]),NameObject('/Bounds'):array([0,0,0,1,1,1,1,0]),NameObject('/GCS'):DictionaryObject({NameObject('/Type'):NameObject('/PROJCS' if projected else '/GEOGCS'),NameObject('/EPSG'):NumberObject(crs)})})
        page[NameObject('/VP')]=ArrayObject([DictionaryObject({NameObject('/Type'):NameObject('/Viewport'),NameObject('/BBox'):array([50,50,550,550]),NameObject('/Measure'):measure})])
    output=io.BytesIO();writer.write(output);return output.getvalue()

class PdfMapTests(unittest.TestCase):
    def test_geographic_import_bounds_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            maps=PdfMaps(directory);item=maps.import_pdf(synthetic_pdf(),'Test map.pdf')
            self.assertAlmostEqual(item['bounds'][0][0],-38,places=5)
            self.assertAlmostEqual(item['bounds'][1][1],145.1,places=5)
            self.assertEqual(PdfMaps(directory).catalog()[0]['id'],item['id'])
            self.assertTrue(maps.image(item['id']).startswith(b'\x89PNG'))
            maps.remove(item['id']);self.assertEqual(maps.catalog(),[])
    def test_projected_import(self):
        with tempfile.TemporaryDirectory() as directory:
            item=PdfMaps(directory).import_pdf(synthetic_pdf(projected=True),'UTM.pdf')
            self.assertIn('32755',item['crs']);self.assertLess(item['bounds'][0][0],item['bounds'][1][0])
    def test_reversed_off_page_frame_keeps_north_up(self):
        from pypdf import PdfReader
        from PIL import Image
        writer=PdfWriter();writer.clone_document_from_reader(PdfReader(io.BytesIO(synthetic_pdf())))
        page=writer.pages[0];vp=page['/VP'][0]
        vp[NameObject('/BBox')]=array([-10,610,610,-10])
        vp['/Measure'][NameObject('/GPTS')]=array([-37.9,145,-38,145,-38,145.1,-37.9,145.1])
        stream=DecodedStreamObject();stream.set_data(b'1 0 0 rg 0 300 600 300 re f 0 0 1 rg 0 0 600 300 re f')
        page[NameObject('/Contents')]=writer._add_object(stream)
        output=io.BytesIO();writer.write(output)
        with tempfile.TemporaryDirectory() as directory:
            maps=PdfMaps(directory);item=maps.import_pdf(output.getvalue(),'reversed.pdf')
            with Image.open(io.BytesIO(maps.image(item['id']))) as image:
                north=image.getpixel((image.width//2,image.height//4))
                south=image.getpixel((image.width//2,image.height*3//4))
                self.assertEqual(north[:3],(255,0,0));self.assertEqual(south[:3],(0,0,255))
            self.assertGreater(item['bounds'][0][1],145)
            self.assertLess(item['bounds'][1][1],145.1)
            self.assertGreater(item['bounds'][0][0],-38)
            self.assertLess(item['bounds'][1][0],-37.9)

    def test_reject_ordinary_pdf_and_bad_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            maps=PdfMaps(directory)
            with self.assertRaisesRegex(ValueError,'geospatial'):maps.import_pdf(synthetic_pdf(False),'plain.pdf')
            with self.assertRaises(ValueError):maps.image('../serve.py')
            with self.assertRaises(ValueError):maps.import_pdf(synthetic_pdf(),'map.pdf',2)

if __name__=='__main__': unittest.main()
