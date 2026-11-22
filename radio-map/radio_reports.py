"""Read received radio reports incrementally from the companion event logs."""
import ast
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import re
import threading

_spec = importlib.util.spec_from_file_location('tait_report_decoder', Path(__file__).resolve().parents[1] / 'tait_to_kml.py')
decoder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(decoder)


class RadioReports:
    def __init__(self):
        self.lock = threading.Lock()
        self.files = {}

    def read(self, paths):
        with self.lock:
            current = set(paths)
            self.files = {path: state for path, state in self.files.items() if path in current}
            for path in current:
                try:
                    size = path.stat().st_size
                    state = self.files.get(path)
                    if state is None or size < state['offset']:
                        state = {'offset': 0, 'source': decoder.SdmSource(), 'reports': {}}
                        self.files[path] = state
                    with path.open('rb') as stream:
                        stream.seek(state['offset'])
                        for line in stream:
                            if not line.endswith(b'\n'):
                                break
                            state['offset'] = stream.tell()
                            try:
                                self.record(state, line.decode('utf-8'))
                            except (ValueError, SyntaxError, UnicodeError, TypeError, IndexError):
                                continue
                except OSError:
                    continue
            latest = {}
            for state in self.files.values():
                for identity, report in state['reports'].items():
                    if identity not in latest or report['time'] > latest[identity]['time']:
                        latest[identity] = report
            return list(latest.values())

    def record(self, state, line):
        timestamp, direction, literal = line.strip().split(' ', 2)
        received = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if direction != 'RX' or received.tzinfo is None:
            return
        received = received.astimezone(timezone.utc)
        frame = ast.literal_eval(literal)
        if not isinstance(frame, bytes) or len(frame) < 5:
            return
        frame = frame.rstrip(b'\r\n')
        data = decoder.payload(frame)
        ident = chr(frame[0])
        caller = state['source'].record(ident, data, received.timestamp())
        if ident not in ('s', '$') or not data:
            return
        identity = caller
        if data[0] & 0x80:
            if len(data) not in (3, 17) or data[0] & 0xF0 != 0x80:
                return
            identity = f'{decoder.bcd(int.from_bytes(data[1:3], "big"), 4):04d}'
            status = ('fix', 'no_fix', 'gps_unavailable', 'gps_error')[data[0] & 3]
            if status == 'fix':
                decoder.parse_avl(data, received)
        elif decoder.parse_dms(data, received):
            status = 'fix'
        elif re.search(rb'\$[A-Z]{2}(?:RMC|GGA),[^$*\r\n]*\*[0-9A-Fa-f]{2}', data):
            status = 'fix' if decoder.parse_fix(data.decode('ascii'), received) else 'no_fix'
        elif identity:
            status = 'unsupported'
        else:
            return
        identity = identity or 'Unknown radio'
        report = {'id': identity, 'time': received.isoformat(), 'status': status}
        previous = state['reports'].get(identity)
        if previous is None or report['time'] >= previous['time']:
            state['reports'][identity] = report
