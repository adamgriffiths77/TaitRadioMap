"""Poll a configured list of TAIT AVL radios and save locations to KML.

Requires tait_to_kml.py alongside this script; importing it does not run or alter
the original logger. Poll command format: Tait TN-856-AN, section 7.
"""
import argparse
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import re
import time

import tait_to_kml as logger


def radio_address(value):
    text = str(value)
    if not re.fullmatch(r'[0-9]{1,8}', text) or int(text) == 0:
        raise ValueError('Radio IDs must contain 1–8 decimal digits and be nonzero')
    return text.zfill(8)


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError('Intervals and timeouts must be finite and greater than zero')
    return number


@dataclass
class Radio:
    address: str
    interval: float
    due: float = 0
    attempted: bool = False


def load_radios(path):
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    rows = config.get('radios') if isinstance(config, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError('Config must contain a nonempty radios list')
    radios = []
    suffixes = set()
    for row in rows:
        if not isinstance(row, dict) or 'id' not in row or 'interval' not in row:
            raise ValueError('Each radio requires id and interval (seconds)')
        address = radio_address(row['id'])
        if address[-4:] in suffixes:
            raise ValueError('Radio IDs must have unique last four digits for AVL response matching')
        suffixes.add(address[-4:])
        radios.append(Radio(address, positive(row['interval'])))
    return radios


def poll_packet(address, return_id=None, lead_in_ms=200):
    if lead_in_ms < 20 or lead_in_ms > 5100 or lead_in_ms % 20:
        raise ValueError('Lead-in delay must be a multiple of 20 ms from 20 to 5100')
    parameters = f'{lead_in_ms // 20:02X}{radio_address(address)}'.encode('ascii')
    parameters += b'\x08' + radio_address(return_id).encode('ascii') if return_id else b'\x00'
    body = b's' + f'{len(parameters):02X}'.encode('ascii') + parameters
    return body + f'{-sum(body) & 255:02X}\r'.encode('ascii')


class Poller:
    """Serialize PC commands and over-air polls; use monotonic scheduling."""
    def __init__(self, radios, send, response_timeout=15, command_timeout=5,
                 gap=2, return_id=None, lead_in_ms=200, once=False):
        self.radios, self.send = radios, send
        self.response_timeout, self.command_timeout = response_timeout, command_timeout
        self.gap, self.return_id, self.lead_in_ms, self.once = gap, return_id, lead_in_ms, once
        self.ready = False
        self.command = None
        self.command_deadline = 0
        self.active = None
        self.response_deadline = 0
        self.pending_query = False
        self.busy = False
        self.ptt = False
        self.not_before = 0
        self.model_received = False

    def issue(self, kind, packet, now):
        self.send(packet)
        self.command, self.command_deadline = kind, now + self.command_timeout
        self.ready = False

    def start(self, now):
        # A local model query establishes command mode/readiness without RF TX.
        self.issue('sync', logger.ccdi_packet('q', '0'), now)

    def prompt(self, now):
        self.ready = True
        if self.command == 'poll':
            self.command = None
        elif self.command == 'sync' and self.model_received:
            self.command = None

    def record(self, ident, data, now):
        if ident == 'm' and self.command == 'sync':
            self.model_received = True
            self.ready = False  # require the post-result prompt
        elif ident == 'p':
            if data == b'05':
                self.busy = True
            elif data == b'06':
                self.busy = False
                self.not_before = max(self.not_before, now + self.gap)
            elif data == b'07':
                self.ptt = True
            elif data == b'08':
                self.ptt = False
                self.not_before = max(self.not_before, now + self.gap)
            if data == b'1E1':
                self.pending_query = True
                self.ready = False
        elif ident == 'r':
            ring = logger.parse_ring(data.decode('ascii'))
            logging.info('RING category %s, call type %s, caller/address %s',
                         ring['category'], ring['call_type'], ring['address'])
            if ring['call_type'] == '4':
                self.pending_query = True
                self.ready = False
        elif ident == 's':
            # Includes pushed data, which can satisfy a queued buffer read.
            self.pending_query = False
            if self.command == 'query':
                self.command = None
            self.ready = False
            if not data:
                logging.warning('Local SDM buffer is empty')
        elif ident == 'e':
            logging.warning('Radio returned CCDI error: %r', data)
            if self.command == 'poll':
                self.finish(now, 'local radio rejected the poll')
            self.command = None
            self.pending_query = False
            self.ready = False

    def finish(self, now, reason):
        if self.active:
            logging.info('Poll %s: %s', self.active.address, reason)
            self.active.due = max(self.active.due, now + self.gap)
            self.active = None
            self.not_before = max(self.not_before, now + self.gap)

    def response(self, suffix, now):
        # Only explicit transmitted identity can complete an active poll.
        if self.active and self.active.address[-4:] == suffix:
            self.finish(now, 'location/status response received')

    def tick(self, now):
        if self.command and now >= self.command_deadline:
            logging.warning('CCDI %s command timed out; waiting for a fresh ready prompt', self.command)
            self.command = None
            self.ready = False
        if self.active and now >= self.response_deadline:
            logging.warning('No matching location response from %s within %.1f seconds',
                            self.active.address, self.response_timeout)
            self.finish(now, 'response timeout')
        if self.command or not self.ready:
            return
        if self.pending_query:
            self.pending_query = False
            self.issue('query', logger.ccdi_packet('q', '1'), now)
            return
        if self.active or self.busy or self.ptt or now < self.not_before:
            return
        available = [r for r in self.radios if r.due <= now and not (self.once and r.attempted)]
        if available:
            radio = min(available, key=lambda r: r.due)
            self.issue('poll', poll_packet(radio.address, self.return_id, self.lead_in_ms), now)
            radio.attempted = True
            radio.due = now + radio.interval
            self.active = radio
            self.response_deadline = now + self.response_timeout
            self.not_before = now + self.gap
            logging.info('Polling %s; interval %.1f seconds', radio.address, radio.interval)

    @property
    def done(self):
        return self.once and all(r.attempted for r in self.radios) and self.active is None and self.command is None and not self.pending_query


class Locations:
    def __init__(self, output, name, existing=None):
        self.output, self.name, self.existing = output, name, existing
        self.fixes, self.descriptions, self.ids = [], [], []
        self.source = logger.SdmSource()

    def record(self, ident, data, now, received):
        caller = self.source.record(ident, data, now)
        if ident not in ('s', '$'):
            return None
        suffix = None
        description = None
        radio_id = None
        if ident == 's' and data and data[0] & 0x80:
            fix, description = logger.parse_avl(data, received)
            suffix = f'{logger.bcd(int.from_bytes(data[1:3], "big"), 4):04d}'
            radio_id = suffix
        else:
            fix = logger.parse_dms(data, received)
            if fix:
                radio_id = caller
                description = ('Direct-send DMS location; timestamp is reception UTC. '
                               f'Caller ID from preceding RING: {caller or "unavailable"}.')
            elif b'$' in data:
                fix = logger.parse_fix(data.decode('ascii'), received)
                radio_id = caller
            if radio_id:
                suffix = radio_id[-4:].zfill(4)
        if fix:
            self.fixes.append(fix)
            self.descriptions.append(description)
            self.ids.append(radio_id)
            logger.write_kml(self.output, self.fixes, self.name, self.descriptions, self.existing, self.ids)
            logging.info('Saved %s: %.6f, %.6f', radio_id or 'Unknown radio', fix[1], fix[2])
        elif data:
            logging.warning('SDM contained no current supported location: %r', data)
        return suffix


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--port', help='Serial port, e.g. COM3')
    parser.add_argument('--baud', type=int, default=9600)
    parser.add_argument('--flow-control', choices=['none', 'xonxoff', 'rtscts'], default='none')
    parser.add_argument('--output', type=Path, default=Path('polled_locations.kml'))
    parser.add_argument('--raw-log', type=Path, default=Path('polled_capture.txt'))
    parser.add_argument('--event-log', type=Path, default=Path('polled_events.txt'))
    parser.add_argument('--append', action='store_true')
    parser.add_argument('--name', default='TAIT polled GPS tracks')
    parser.add_argument('--response-timeout', type=float, default=15)
    parser.add_argument('--command-timeout', type=float, default=5)
    parser.add_argument('--poll-gap', type=float, default=2, help='Minimum gap in seconds between RF polls/after busy')
    parser.add_argument('--lead-in-ms', type=int, default=200)
    parser.add_argument('--return-id', help='Optional eight-digit response destination; otherwise radio uses its configured dispatcher')
    parser.add_argument('--once', action='store_true', help='Poll every listed radio once, then exit')
    parser.add_argument('--dry-run', action='store_true', help='Print poll commands without opening a port or writing files')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format='%(levelname)s: %(message)s')
    try:
        radios = load_radios(args.config)
        for value in (args.response_timeout, args.command_timeout, args.poll_gap):
            positive(value)
        if args.baud <= 0:
            raise ValueError('Baud rate must be positive')
        packets = [poll_packet(r.address, args.return_id, args.lead_in_ms) for r in radios]
        if args.dry_run:
            for radio, packet in zip(radios, packets):
                print(f'{radio.address} every {radio.interval:g}s: {packet!r} | {packet.hex(" ")}')
            return 0
        if not args.port:
            raise ValueError('--port is required unless using --dry-run')
        paths = [args.config, args.output, args.raw_log, args.event_log]
        if len({p.resolve() for p in paths}) != len(paths):
            raise ValueError('Config, KML, raw log and event log must use different files')
        if args.output.exists() and not args.append:
            raise ValueError('KML exists; use --append or a new --output filename')
        existing = logger.read_kml(args.output) if args.output.exists() else None
        try:
            import serial
        except ImportError:
            raise ValueError('Install pyserial: python -m pip install -r requirements.txt')
        locations = Locations(args.output, args.name, existing)
        with ExitStack() as stack:
            stream = stack.enter_context(serial.Serial(args.port, args.baud, timeout=0.1, write_timeout=2,
                                        xonxoff=args.flow_control == 'xonxoff', rtscts=args.flow_control == 'rtscts'))
            raw = stack.enter_context(args.raw_log.open('ab'))
            events = stack.enter_context(args.event_log.open('a', encoding='utf-8'))
            def event(direction, data):
                events.write(f'{datetime.now(timezone.utc).isoformat()} {direction} {data!r}\n')
                events.flush()
            def send(packet):
                if stream.write(packet) != len(packet):
                    raise OSError('Incomplete serial write')
                event('TX', packet)
                logging.info('TX %r', packet)
            if existing is None:
                logger.write_kml(args.output, [], args.name)
            poller = Poller(radios, send, args.response_timeout, args.command_timeout,
                            args.poll_gap, args.return_id, args.lead_in_ms, args.once)
            reader = logger.FrameReader()
            poller.start(time.monotonic())
            while not poller.done:
                chunk = stream.read(1)
                now = time.monotonic()
                if chunk:
                    raw.write(chunk)
                    raw.flush()
                    try:
                        framed = reader.feed(chunk)
                        if framed:
                            kind, frame = framed
                            event('RX', frame)
                            logging.debug('RX %r', frame)
                            if kind == 'prompt':
                                poller.prompt(now)
                            else:
                                data = logger.payload(frame)
                                ident = chr(frame[0])
                                poller.record(ident, data, now)
                                suffix = locations.record(ident, data, now, datetime.now(timezone.utc))
                                if suffix:
                                    poller.response(suffix, now)
                    except (ValueError, UnicodeError) as exc:
                        logging.warning('Ignored record: %s', exc)
                # Never transmit midway through an incoming frame.
                if not reader.buffer:
                    poller.tick(now)
        return 0
    except KeyboardInterrupt:
        logging.info('Stopped; existing KML and completed location writes are preserved')
        return 0
    except (OSError, ValueError, TypeError) as exc:
        logging.error('%s', exc)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
