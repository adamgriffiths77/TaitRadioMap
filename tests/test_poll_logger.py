from collections import deque
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import tait_poll_to_kml as poll
import tait_to_kml as logger


AVL = bytes.fromhex('80 00 30 87 c0 97 93 7d 46 62 b4 59 95 79 a9 00 00')


def frame(ident, parameters):
    body = ident.encode() + f'{len(parameters):02X}'.encode() + parameters
    return body + f'{-sum(body) & 255:02X}\r'.encode()


class PollTests(unittest.TestCase):
    def ready(self, controller, now=0):
        controller.start(now)
        controller.prompt(now + .01)  # acceptance alone is insufficient
        controller.record('m', b'test', now + .02)
        controller.prompt(now + .03)

    def test_protocol_examples(self):
        self.assertEqual(poll.poll_packet('8001'), b's0B0A00008001\x0021\r')
        self.assertEqual(poll.poll_packet('8001', '12345678'), b's130A00008001\x081234567883\r')
        self.assertEqual(logger.payload(poll.poll_packet('3000030')[:-1])[2:10], b'03000030')
        for bad in ['0', '*', '300003000', '12-3']:
            with self.assertRaises(ValueError):
                poll.poll_packet(bad)
        with self.assertRaises(ValueError):
            poll.poll_packet('30', lead_in_ms=21)

    def test_serialization_matching_and_intervals(self):
        sent = []
        controller = poll.Poller([poll.Radio('03000030', 60), poll.Radio('03000029', 120)], sent.append)
        controller.start(0)
        controller.prompt(.01)
        controller.tick(.02)
        self.assertEqual(len(sent), 1)
        controller.record('m', b'test', .03)
        controller.prompt(.04)
        controller.tick(1)
        self.assertEqual(sent[-1], poll.poll_packet('3000030'))
        controller.prompt(1.1)
        controller.tick(2)
        self.assertEqual(len(sent), 2)
        controller.response('9999', 2)
        self.assertIsNotNone(controller.active)
        controller.record('p', b'1E1', 3)
        controller.tick(3)
        self.assertEqual(len(sent), 2)
        controller.prompt(3.1)
        controller.tick(3.2)
        self.assertEqual(sent[-1], b'q011FD\r')
        controller.prompt(3.3)
        controller.tick(3.4)
        self.assertEqual(controller.command, 'query')
        controller.record('s', AVL, 3.5)
        controller.response('0030', 3.5)
        controller.prompt(3.6)
        controller.tick(6)
        self.assertEqual(sent[-1], poll.poll_packet('3000029'))
        controller.prompt(6.1)
        controller.response('0029', 7)
        controller.tick(30)
        self.assertEqual(len(sent), 4)
        controller.tick(61)
        self.assertEqual(sent[-1], poll.poll_packet('3000030'))

    def test_manual_poll_waits_for_active_response_and_gap(self):
        sent = []
        first, second = poll.Radio('03000030', 60), poll.Radio('03000029', 120, due=100)
        controller = poll.Poller([first, second], sent.append)
        self.ready(controller)
        controller.tick(1)
        controller.prompt(1.1)
        controller.request(second.address)
        controller.request(second.address)
        controller.tick(2)
        self.assertEqual(sent[-1], poll.poll_packet(first.address))
        controller.response('0030', 3)
        controller.tick(4)
        self.assertEqual(len(sent), 2)
        controller.tick(5)
        self.assertEqual(sent[-1], poll.poll_packet(second.address))
        controller.prompt(5.1)
        controller.response('0029', 6)
        controller.tick(8)
        self.assertEqual(len(sent), 3)

    def test_busy_ptt_timeout_and_once(self):
        sent = []
        controller = poll.Poller([poll.Radio('03000030', 60)], sent.append, once=True)
        self.ready(controller)
        controller.record('p', b'05', 1)
        controller.tick(1)
        self.assertEqual(len(sent), 1)
        controller.record('p', b'06', 2)
        controller.record('p', b'07', 3)
        controller.tick(5)
        self.assertEqual(len(sent), 1)
        controller.record('p', b'08', 6)
        controller.tick(7)
        self.assertEqual(len(sent), 1)
        controller.tick(8)
        controller.prompt(8.1)
        controller.tick(24)
        self.assertTrue(controller.done)
        controller.tick(100)
        self.assertEqual(len(sent), 2)

    def test_command_timeout_does_not_flood(self):
        sent = []
        controller = poll.Poller([poll.Radio('03000030', 60)], sent.append)
        controller.start(0)
        controller.tick(6)
        controller.tick(100)
        self.assertEqual(len(sent), 1)
        self.assertFalse(controller.ready)

    def test_config_validation_and_dry_run_no_files(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'radios.json'
            config.write_text(json.dumps({'radios': [{'id': '3000030', 'interval': 60}]}))
            output = Path(directory) / 'unused.kml'
            with patch.object(sys, 'argv', ['poll', '--config', str(config), '--output', str(output), '--dry-run']), redirect_stdout(io.StringIO()) as text:
                self.assertEqual(poll.main(), 0)
            self.assertIn('03000030 every 60s', text.getvalue())
            self.assertFalse(output.exists())
            for rows in [[], [{'id': '30', 'interval': 0}], [{'id': '30', 'interval': float('nan')}],
                         [{'id': '3000030', 'interval': 60}, {'id': '4000030', 'interval': 60}]]:
                config.write_text(json.dumps({'radios': rows}))
                with self.assertRaises(ValueError):
                    poll.load_radios(config)

    def test_two_radio_serial_session_outputs_and_append(self):
        original_hash = hashlib.sha256(Path(logger.__file__).read_bytes()).digest()
        class FakeSerial:
            def __init__(self):
                self.rx = deque()
                self.sent = []
                self.suffix = '0030'
                self.clock = 0
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, count):
                self.clock += .01
                if self.clock > 100:
                    raise AssertionError('Polling session failed to complete')
                return bytes([self.rx.popleft()]) if self.rx else b''
            def write(self, packet):
                self.sent.append(packet)
                if packet == b'q010FE\r':
                    self.rx.extend(b'.' + frame('m', b'test') + b'.')
                elif packet[:1] == b's':
                    self.suffix = logger.payload(packet[:-1])[6:10].decode()
                    self.rx.extend(b'.p0205C9\r.p031E186\r.')
                elif packet == b'q011FD\r':
                    data = AVL[:1] + bytes.fromhex(self.suffix) + AVL[3:]
                    self.rx.extend(b'.' + frame('s', data) + b'.p0206C8\r.')
                return len(packet)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, output, raw, events = [root / name for name in ('radios.json', 'trip.kml', 'raw.txt', 'events.txt')]
            config.write_text(json.dumps({'radios': [{'id': '3000030', 'interval': 60}, {'id': '3000029', 'interval': 120}]}))
            argv = ['poll', '--config', str(config), '--port', 'TEST', '--output', str(output), '--raw-log', str(raw), '--event-log', str(events), '--once']
            for append in (False, True):
                serial = FakeSerial()
                with patch.object(sys, 'argv', argv + (['--append'] if append else [])), patch.dict(sys.modules, {'serial': types.SimpleNamespace(Serial=lambda *a, **k: serial)}), patch.object(poll.time, 'monotonic', lambda: serial.clock):
                    self.assertEqual(poll.main(), 0)
                self.assertEqual(len([p for p in serial.sent if p.startswith(b's')]), 2)
            ns = {'k': 'http://www.opengis.net/kml/2.2'}
            marks = ET.parse(output).findall('.//k:Placemark', ns)
            self.assertEqual([m.find('k:name', ns).text for m in marks], ['0030', '0029', '0030', '0029'])
            self.assertIn('TX', events.read_text())
            self.assertGreater(raw.stat().st_size, 0)
        self.assertEqual(hashlib.sha256(Path(logger.__file__).read_bytes()).digest(), original_hash)


if __name__ == '__main__':
    unittest.main()
