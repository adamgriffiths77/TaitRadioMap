import tempfile
import unittest
from unittest.mock import patch
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET
import tait_to_kml as logger


RMC = '$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A'
AVL = bytes.fromhex('80 00 30 87 c0 97 93 7d 46 62 b4 59 95 79 a9 00 00')
DMS = b'S  37\xb054\x2740.1"\rE 145\xb019\x2733.0"'


def binary_packet(data):
    body = b's' + f'{len(data):02X}'.encode() + data
    return body + f'{-sum(body) & 255:02X}'.encode() + b'\r'


class LoggerTests(unittest.TestCase):
    def test_direct_send_location(self):
        self.assertEqual(binary_packet(DMS)[-3:], b'C3\r')
        reference = datetime(2026, 10, 29, 9, 46, 52, tzinfo=timezone.utc)
        fix = logger.parse_dms(DMS, reference)
        self.assertEqual(fix[0], reference)
        self.assertAlmostEqual(fix[1], -(37 + 54/60 + 40.1/3600))
        self.assertAlmostEqual(fix[2], 145 + 19/60 + 33/3600)
        with self.assertRaises(ValueError):
            logger.parse_dms(DMS.replace(b'40.1', b'60.1'))
        self.assertIsNone(logger.parse_dms(b'ordinary SDM text'))
        reader = logger.FrameReader()
        records = [result for byte in binary_packet(DMS) if (result := reader.feed(bytes([byte])))]
        self.assertEqual(len(records), 1)
        self.assertEqual(logger.payload(records[0][1]), DMS)

    def test_direct_sender_context_expires_and_is_consumed(self):
        source = logger.SdmSource()
        source.record('r', b'54000FF3000029', 0)
        self.assertEqual(source.record('s', DMS, 0.1), '3000029')
        self.assertIsNone(source.record('s', DMS, 0.2))
        for ident, data in [('p', b'05'), ('p', b'1E1'), ('e', b'006'), ('r', b'50000FF3000030')]:
            source.record('r', b'54000FF3000029', 1)
            source.record(ident, data, 1.1)
            self.assertIsNone(source.record('s', DMS, 1.2))
        source.record('r', b'54000FF3000029', 2)
        self.assertIsNone(source.record('s', DMS, 8))

    def test_captured_dmr_sdm_ring_requests_buffer(self):
        text = logger.payload('r0E54000FF300002936')
        self.assertEqual(logger.parse_ring(text),
                         {'category': '5', 'call_type': '4', 'address': '3000029'})
        sent = []
        retrieval = logger.SdmRetrieval(sent.append)
        retrieval.record('r', text, 0)
        self.assertEqual(sent, [])
        retrieval.prompt(0.1)
        self.assertEqual(sent, [b'q011FD\r'])
        retrieval.record('s', b'not a location', 0.2)
        self.assertIsNone(retrieval.deadline)
        voice = logger.SdmRetrieval(sent.append)
        voice.record('r', '50000FF3000029', 1)
        voice.prompt(1)
        self.assertEqual(len(sent), 1)
        with self.assertRaises(ValueError):
            logger.parse_ring('54')

    def test_append_preserves_previous_sessions_and_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source, output = folder / 'input.txt', folder / 'trip.kml'
            raw, events = folder / 'raw.txt', folder / 'events.txt'
            source.write_bytes(logger.ccdi_packet('s', RMC))
            argv = ['logger', '--input', str(source), '--output', str(output),
                    '--raw-log', str(raw), '--event-log', str(events)]
            with patch.object(sys, 'argv', argv):
                self.assertEqual(logger.main(), 0)
            old_events = events.read_bytes()
            # Preserve arbitrary existing metadata as well as point descriptions.
            tree = ET.parse(output)
            document = tree.getroot().find('{http://www.opengis.net/kml/2.2}Document')
            ET.SubElement(document, '{http://www.opengis.net/kml/2.2}description').text = 'Keep this metadata'
            tree.write(output, encoding='utf-8', xml_declaration=True)
            before = output.read_bytes()
            with patch.object(sys, 'argv', argv), self.assertRaises(SystemExit), patch('sys.stderr'):
                logger.main()
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(events.read_bytes(), old_events)
            for _ in range(2):
                with patch.object(sys, 'argv', argv + ['--append']):
                    self.assertEqual(logger.main(), 0)
            ns = {'k': 'http://www.opengis.net/kml/2.2'}
            tree = ET.parse(output)
            self.assertEqual(len(tree.findall('.//k:Point', ns)), 3)
            self.assertEqual(len(tree.findall('.//k:Folder', ns)), 2)
            self.assertEqual(tree.find('./k:Document/k:description', ns).text, 'Keep this metadata')
            self.assertEqual(raw.read_bytes(), source.read_bytes() * 3)
            self.assertTrue(events.read_bytes().startswith(old_events))
            # With no new fixes, append leaves the existing file byte-for-byte intact.
            source.write_bytes(b'')
            before = output.read_bytes()
            with patch.object(sys, 'argv', argv + ['--append']):
                self.assertEqual(logger.main(), 0)
            self.assertEqual(output.read_bytes(), before)

    def test_append_rejects_invalid_kml_before_touching_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source, output, raw = folder / 'input.txt', folder / 'trip.kml', folder / 'raw.txt'
            source.write_bytes(logger.ccdi_packet('s', RMC))
            raw.write_bytes(b'original')
            for invalid in (b'<broken', b'<kml/>'):
                output.write_bytes(invalid)
                argv = ['logger', '--input', str(source), '--output', str(output),
                        '--raw-log', str(raw), '--append']
                with patch.object(sys, 'argv', argv):
                    self.assertEqual(logger.main(), 1)
                self.assertEqual(output.read_bytes(), invalid)
                self.assertEqual(raw.read_bytes(), b'original')

    def test_captured_binary_report(self):
        packet = binary_packet(AVL)
        self.assertEqual(packet[-3:], b'21\r')
        self.assertEqual(logger.payload(packet[:-1]), AVL)
        fix, description = logger.parse_avl(AVL, datetime(2026, 10, 29, tzinfo=timezone.utc))
        self.assertEqual(fix[0].isoformat(), '2026-10-29T07:40:17+00:00')
        self.assertAlmostEqual(fix[1], -(37 + 54.662 / 60))
        self.assertAlmostEqual(fix[2], 145 + 19.579 / 60)
        self.assertIn('0030', description)
        sent = []
        retrieval = logger.SdmRetrieval(sent.append)
        retrieval.record('p', '1E1', 0)
        retrieval.prompt(0)
        retrieval.record('s', logger.payload(packet[:-1]), 0.03)
        with self.assertNoLogs(level='WARNING'):
            retrieval.tick(6)
        self.assertIsNone(retrieval.deadline)

    def test_documented_avl_example_and_invalid_data(self):
        data = bytes.fromhex('80 80 01 84 83 d8 a5 88 20 22 a2 09 53 90 a6 00 10')
        fix, description = logger.parse_avl(data, datetime(2026, 10, 26, tzinfo=timezone.utc))
        self.assertAlmostEqual(fix[1], 58 + 2.022 / 60)
        self.assertAlmostEqual(fix[2], -(20 + 15.390 / 60))
        self.assertIn('8001', description)
        self.assertIn('1.0 knots', description)
        self.assertIsNone(logger.parse_avl(bytes([0x81]) + AVL[1:])[0])
        self.assertIsNone(logger.parse_avl(bytes.fromhex('82 00 30'))[0])
        for bad in (AVL[:10], AVL[:8] + b'\xfa' + AVL[9:], AVL[:3] + b'\xff' + AVL[4:]):
            with self.assertRaises(ValueError):
                logger.parse_avl(bad)
        damaged = bytearray(binary_packet(AVL)[:-1])
        damaged[5] ^= 1
        with self.assertRaises(ValueError):
            logger.payload(bytes(damaged))

    def test_binary_framing_embedded_delimiters(self):
        data = b'\r\n.\x00\xff'
        packet = binary_packet(data)
        reader = logger.FrameReader()
        found = [result for byte in b'.' + packet + b'.' if (result := reader.feed(bytes([byte]))) is not None]
        self.assertEqual(found, [('prompt', b'.'), ('record', packet[:-1]), ('prompt', b'.')])
        self.assertEqual(logger.payload(found[1][1]), data)

    def test_all_four_captured_reports(self):
        payloads = [
            '80 00 30 87 c0 97 93 7d 46 62 b4 59 95 79 a9 00 00',
            '80 00 30 87 c0 c7 93 7d 46 62 b4 59 95 84 a9 00 03',
            '80 00 30 87 c1 97 93 7d 46 63 b4 59 95 85 a9 00 02',
            '80 00 30 87 c1 c6 93 7d 46 63 b4 59 95 83 a9 00 00',
        ]
        reference = datetime(2026, 10, 29, tzinfo=timezone.utc)
        fixes = [logger.parse_avl(bytes.fromhex(data), reference)[0] for data in payloads]
        self.assertEqual([fix[0].strftime('%H:%M:%S') for fix in fixes],
                         ['07:40:17', '07:40:47', '07:41:17', '07:41:46'])
        self.assertAlmostEqual(fixes[-1][1], -37.91105)
        self.assertAlmostEqual(fixes[-1][2], 145.3263833333)

    def test_avl_month_rollover(self):
        data = bytearray(AVL)
        data[14] = 0xB1  # day 31
        fix, _ = logger.parse_avl(data, datetime(2026, 11, 1, tzinfo=timezone.utc))
        self.assertEqual(fix[0].date().isoformat(), '2026-10-31')

    def test_retrieval_waits_for_prompt_and_response(self):
        sent = []
        retrieval = logger.SdmRetrieval(sent.append)
        retrieval.record('p', '1E1', 0)
        self.assertEqual(sent, [])
        retrieval.prompt(1)
        self.assertEqual(sent, [b'q011FD\r'])
        retrieval.prompt(2)  # acceptance prompt, not a response
        retrieval.record('p', '1E1', 2)
        retrieval.prompt(2)
        self.assertEqual(len(sent), 1)
        retrieval.record('s', RMC, 3)
        self.assertEqual(len(sent), 1)
        retrieval.prompt(3)
        self.assertEqual(len(sent), 2)

    def test_timeout_does_not_retry_and_error_recovers(self):
        sent = []
        retrieval = logger.SdmRetrieval(sent.append)
        retrieval.record('p', '1E1', 0)
        retrieval.prompt(0)
        retrieval.tick(6)
        retrieval.prompt(7)
        self.assertEqual(len(sent), 1)
        retrieval.record('p', '1E1', 8)
        retrieval.prompt(8)
        retrieval.record('e', '006', 9)
        retrieval.prompt(9)
        self.assertIsNone(retrieval.deadline)
        self.assertEqual(len(sent), 2)

    def test_serial_notification_query_response_to_kml(self):
        data = (b'p0205C9\r.r0E54000FF300002936\r..' + logger.ccdi_packet('s', RMC)
                + b'.p031E186\r..' + binary_packet(AVL)
                + b'.p0205C9\r.r0E54000FF300002936\r..' + binary_packet(DMS) + b'.')
        class FakeSerial:
            def __init__(self):
                self.data = iter(data)
                self.sent = []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, count):
                try:
                    return bytes([next(self.data)])
                except StopIteration:
                    raise KeyboardInterrupt
            def write(self, command):
                self.sent.append(command)
                return len(command)
        stream = FakeSerial()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'trip.kml'
            capture = Path(directory) / 'capture.txt'
            events = Path(directory) / 'events.txt'
            argv = ['logger', '--port', 'COM_TEST', '--output', str(output),
                    '--raw-log', str(capture), '--event-log', str(events)]
            with patch.object(sys, 'argv', argv), patch.dict(sys.modules, {'serial': types.SimpleNamespace(Serial=lambda *a, **k: stream)}):
                self.assertEqual(logger.main(), 0)
            self.assertEqual(stream.sent, [b'q011FD\r'] * 3)
            self.assertEqual(capture.read_bytes(), data)
            self.assertIn('TX', events.read_text())
            self.assertEqual(len(ET.parse(output).findall('.//{http://www.opengis.net/kml/2.2}Point')), 3)
            ns = {'k': 'http://www.opengis.net/kml/2.2'}
            marks = ET.parse(output).findall('.//k:Placemark', ns)
            points = [mark for mark in marks if mark.find('k:Point', ns) is not None]
            self.assertEqual([mark.find('k:name', ns).text for mark in points], ['Unknown radio', '0030', '3000029'])
            self.assertTrue(all(mark.find('k:TimeStamp/k:when', ns) is not None for mark in points))
            self.assertIn('reception/reference UTC', points[-1].find('k:description', ns).text)

    def test_tracks_do_not_join_different_radio_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'tracks.kml'
            fix = logger.parse_fix(RMC)
            logger.write_kml(output, [fix] * 4, 'test', radio_ids=['0030', '3000029', '0030', '3000029'])
            ns = {'k': 'http://www.opengis.net/kml/2.2'}
            marks = ET.parse(output).findall('.//k:Placemark', ns)
            tracks = [mark for mark in marks if mark.find('k:LineString', ns) is not None]
            self.assertEqual([mark.find('k:name', ns).text for mark in tracks], ['0030', '3000029'])
            self.assertTrue(all(len(mark.find('k:LineString/k:coordinates', ns).text.split()) == 2 for mark in tracks))

    def test_ccdi_and_nmea(self):
        packet = logger.ccdi_packet('s', RMC).decode().strip()
        fix = logger.parse_fix(logger.payload(packet))
        self.assertAlmostEqual(fix[1], 48.1173)
        self.assertAlmostEqual(fix[2], 11.5166666667)
        self.assertEqual(fix[0].isoformat(), '1994-03-23T12:35:19+00:00')

    def test_bad_checksums_and_lengths(self):
        for packet in ['s02Hi00', 's03Hi7A']:
            with self.assertRaises(ValueError):
                logger.payload(packet)
        with self.assertRaises(ValueError):
            logger.parse_fix(RMC[:-2] + '00')

    def test_coordinates(self):
        self.assertAlmostEqual(logger.coordinate('3351.000', 'S', True), -33.85)
        for value in ['9060.0', '9100.0', 'nan']:
            with self.assertRaises(ValueError):
                logger.coordinate(value, 'N', True)

    def test_kml(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.kml'
            fix = logger.parse_fix(RMC)
            logger.write_kml(path, [fix, fix], 'A & B')
            root = ET.parse(path)
            ns = {'k': 'http://www.opengis.net/kml/2.2'}
            self.assertEqual(len(root.findall('.//k:Point', ns)), 2)
            self.assertIn('11.51666667,48.11730000', root.find('.//k:coordinates', ns).text)


if __name__ == '__main__':
    unittest.main()
