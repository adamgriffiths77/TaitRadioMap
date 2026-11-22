from pathlib import Path
import tempfile
import unittest

from radio_reports import RadioReports
from serve import collect_positions


def event(second, data):
    body = b's' + f'{len(data):02X}'.encode() + data
    frame = body + f'{-sum(body) & 255:02X}'.encode()
    return f'2026-11-23T01:00:{second:02d}+00:00 RX {frame!r}\n'


class RadioReportTests(unittest.TestCase):
    def test_no_fix_updates_reception_time_without_creating_a_position(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'radio-test-events.txt'
            path.write_text(event(1, bytes.fromhex('80003087c097937d4662b4599579a90000')))
            reader = RadioReports()
            self.assertEqual(reader.read([path])[0]['status'], 'fix')
            no_fix = event(2, bytes.fromhex('810030'))
            with path.open('a') as stream:
                stream.write(no_fix[:-1])
            self.assertEqual(reader.read([path])[0]['status'], 'fix')
            with path.open('a') as stream:
                stream.write('\n')
            reports = reader.read([path])
            self.assertEqual(reports, [{'id': '0030', 'time': '2026-11-23T01:00:02+00:00', 'status': 'no_fix'}])
            self.assertEqual(RadioReports().read([path]), reports)

            class Controller:
                def files(self): return []
                def reports(self): return reports

            payload = collect_positions([], controller=Controller())
            self.assertEqual(payload['reports'], reports)
            self.assertEqual(payload['points'], [])
            with path.open('a') as stream:
                stream.write(event(3, bytes.fromhex('80003087c097937d4662b4599579a90000')))
            self.assertEqual(reader.read([path])[0]['status'], 'fix')

    def test_local_commands_and_corrupt_records_do_not_update_last_heard(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'radio-test-events.txt'
            valid = event(1, bytes.fromhex('820029'))
            path.write_text(valid + event(2, bytes.fromhex('810030')).replace(' RX ', ' TX ')
                            + "2026-11-23T01:00:03+00:00 RX b's03810030FF'\n")
            reader = RadioReports()
            self.assertEqual(reader.read([path]), [{'id': '0029', 'time': '2026-11-23T01:00:01+00:00', 'status': 'gps_unavailable'}])
            path.write_text(event(4, bytes.fromhex('830030')))
            self.assertEqual(reader.read([path])[0]['status'], 'gps_error')
