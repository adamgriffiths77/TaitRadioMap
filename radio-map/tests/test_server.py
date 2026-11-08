import importlib.util
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).parents[1]))

spec = importlib.util.spec_from_file_location('map_server', Path(__file__).parents[1] / 'serve.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class KmlTests(unittest.TestCase):
    def test_optional_missing_files_do_not_flag_healthy_live_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            missing = path / 'trip2.kml'
            live = path / 'radio-live.kml'
            live.write_text('<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>0030</name><TimeStamp><when>2026-10-31T01:00:00Z</when></TimeStamp><Point><coordinates>145,-37,0</coordinates></Point></Placemark></Document></kml>')
            class Controller:
                def files(self): return [live]
            data = server.collect_positions([], [missing], Controller())
            self.assertEqual(data['errors'], [])
            self.assertEqual([p['id'] for p in data['points']], ['0030'])
            self.assertEqual(len(server.collect_positions([missing], [missing])['errors']), 1)
            missing.write_text('broken KML')
            self.assertEqual(len(server.collect_positions([], [missing])['errors']), 1)
            missing.write_text(live.read_text())
            self.assertEqual(len(server.collect_positions([], [missing])['points']), 1)

    def test_old_names_and_session_points(self):
        xml = '''<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
        <Placemark><name>2026-10-29T07:40:17Z</name><description>Radio ID suffix: 0030 (last four digits only)</description>
        <TimeStamp><when>2026-10-29T07:40:17Z</when></TimeStamp><Point><coordinates>145.3,-37.9,0</coordinates></Point></Placemark>
        <Folder><Placemark><name>3000029</name><TimeStamp><when>2026-10-29T07:41:17Z</when></TimeStamp><Point><coordinates>145.4,-37.8,0</coordinates></Point></Placemark></Folder>
        <Placemark><name>Ignore track</name><LineString><coordinates>145,-37 146,-38</coordinates></LineString></Placemark>
        <Placemark><TimeStamp><when>bad</when></TimeStamp><Point><coordinates>nan,0</coordinates></Point></Placemark>
        </Document></kml>'''
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.kml'; path.write_text(xml)
            points = server.read_positions(path)
        self.assertEqual([p['id'] for p in points], ['0030', '3000029'])
        self.assertNotEqual(points[0]['session'], points[1]['session'])
        self.assertEqual(points[0]['time'], '2026-10-29T07:40:17+00:00')


if __name__ == '__main__':
    unittest.main()
