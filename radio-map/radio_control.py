"""Local-only process controller for the original TAIT command-line scripts."""
from collections import deque
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parent


def serial_ports():
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise ValueError('Install pyserial in the Python used for this server: python -m pip install -r requirements.txt') from exc
    return [{'device': p.device, 'description': p.description} for p in list_ports.comports()]


def validate_settings(settings, ports):
    if not isinstance(settings, dict):
        raise ValueError('Connection settings must be an object')
    device = settings.get('port')
    if device not in [p['device'] for p in ports]:
        raise ValueError('Select an available serial port, then refresh the port list if needed')
    baud = settings.get('baud', 9600)
    if isinstance(baud, bool) or not isinstance(baud, int) or baud not in (1200, 2400, 4800, 9600, 14400, 19200, 28800, 38400, 57600, 115200):
        raise ValueError('Select a supported baud rate')
    mode = settings.get('mode', 'listen')
    if mode not in ('listen', 'poll'):
        raise ValueError('Mode must be listen or poll')
    flow = settings.get('flow', 'none')
    if flow not in ('none', 'xonxoff', 'rtscts'):
        raise ValueError('Unsupported flow control')
    radios = settings.get('radios', [])
    if mode == 'poll':
        if not isinstance(radios, list) or not 1 <= len(radios) <= 100:
            raise ValueError('Enter between 1 and 100 radios to poll')
        suffixes = set()
        for row in radios:
            if not isinstance(row, dict):
                raise ValueError('Invalid poll list')
            identity, interval = str(row.get('id', '')), row.get('interval')
            if not re.fullmatch(r'[0-9]{1,8}', identity) or int(identity) == 0:
                raise ValueError('Radio IDs must contain 1–8 digits and be nonzero')
            if isinstance(interval, bool) or not isinstance(interval, (float, int)) or not math.isfinite(interval) or interval < 1:
                raise ValueError('Each polling interval must be at least 1 second')
            suffix = identity.zfill(8)[-4:]
            if suffix in suffixes:
                raise ValueError('Polling IDs must have unique last four digits')
            suffixes.add(suffix)
    return {'port': device, 'baud': baud, 'mode': mode, 'flow': flow,
            'radios': radios if mode == 'poll' else []}


class RadioController:
    def __init__(self, directory=None, port_provider=serial_ports, launcher=subprocess.Popen):
        self.directory = Path(directory) if directory else ROOT / 'runtime'
        self.port_provider, self.launcher = port_provider, launcher
        self.lock = threading.RLock()
        self.process = None
        self.stopping = False
        self.settings = None
        self.logs = deque(maxlen=150)
        self.started = None
        self.output = None

    def status(self):
        with self.lock:
            code = self.process.poll() if self.process else None
            return {'running': self.process is not None and code is None, 'stopping': self.stopping,
                    'settings': self.settings, 'started': self.started, 'exit_code': code,
                    'output': self.output.name if self.output else None, 'logs': list(self.logs)}

    def files(self):
        return sorted(self.directory.glob('radio-*.kml')) if self.directory.exists() else []

    def start(self, settings):
        with self.lock:
            if self.stopping or (self.process and self.process.poll() is None):
                raise ValueError('A radio connection is already active; stop it before changing settings')
            settings = validate_settings(settings, self.port_provider())
            self.directory.mkdir(parents=True, exist_ok=True)
            stem = 'radio-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
            output = self.directory / (stem + '.kml')
            script = 'tait_poll_to_kml.py' if settings['mode'] == 'poll' else 'tait_to_kml.py'
            command = [sys.executable, '-u', str(ROOT.parent / script), '--port', settings['port'],
                       '--baud', str(settings['baud']), '--flow-control', settings['flow'],
                       '--output', str(output), '--raw-log', str(self.directory / (stem + '-capture.txt')),
                       '--event-log', str(self.directory / (stem + '-events.txt')), '--verbose']
            if settings['mode'] == 'poll':
                config = self.directory / (stem + '-radios.json')
                config.write_text(json.dumps({'radios': settings['radios']}), encoding='utf-8')
                command += ['--config', str(config), '--manual-poll-stdin']
            stdin = subprocess.PIPE if settings['mode'] == 'poll' else None
            process = self.launcher(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=stdin,
                                    text=True, encoding='utf-8', errors='replace',
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.process, self.settings, self.output = process, settings, output
            self.started = datetime.now(timezone.utc).isoformat()
            self.logs.clear()
            threading.Thread(target=self._read_logs, args=(process,), daemon=True).start()
            return self.status()

    def request_poll(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r'[0-9]{1,8}', identity):
            raise ValueError('Select a radio with a numeric ID')
        with self.lock:
            process = self.process
            if self.stopping or not process or process.poll() is not None or self.settings['mode'] != 'poll':
                raise ValueError('Start a Poll radios session in Radio connection first')
            addresses = [str(row['id']).zfill(8) for row in self.settings['radios']]
            address = identity.zfill(8)
            if len(identity) == 4:
                address = next((item for item in addresses if item.endswith(identity)), address)
            if address not in addresses:
                raise ValueError('Add this radio’s full ID to the poll list and restart the poll session')
            process.stdin.write(address + '\n')
            process.stdin.flush()
            return {'id': address.lstrip('0')}

    def _read_logs(self, process):
        try:
            for line in process.stdout:
                with self.lock:
                    if process is self.process:
                        self.logs.append(line.rstrip())
        finally:
            process.stdout.close()
            if process.stdin:
                with self.lock:
                    process.stdin.close()

    def stop(self):
        with self.lock:
            if self.stopping:
                raise ValueError('The radio connection is already stopping')
            self.stopping = True
            process = self.process
        try:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        finally:
            with self.lock:
                self.stopping = False
        return self.status()
