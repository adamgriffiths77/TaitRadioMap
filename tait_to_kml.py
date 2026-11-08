"""Receive CCDI binary AVL or NMEA and maintain a readable KML file."""
import argparse
import copy
from datetime import datetime, timezone
import logging
import math
import os
from pathlib import Path
import re
import tempfile
import time
import xml.etree.ElementTree as ET


def ccdi_packet(ident, parameters):
    body = f"{ident}{len(parameters):02X}{parameters}"
    return (body + f"{(-sum(body.encode('ascii'))) & 255:02X}\r").encode('ascii')


def parse_ring(text):
    """Decode the RING header; retain optional destination/caller address text."""
    if len(text) < 7 or not re.fullmatch(r'[0125][0-9]{4}[0-9A-Fa-f]{2}', text[:7]):
        raise ValueError('Invalid CCDI RING header')
    address = text[7:]
    if address and not re.fullmatch(r'[0-9A-Za-z*\-]+', address):
        raise ValueError('Invalid CCDI RING address')
    return {'category': text[0], 'call_type': text[1],
            'address': address or 'not supplied'}


class SdmRetrieval:
    """Queue one local buffer query, gated by a standalone CCDI prompt.

    A command-acceptance prompt does not complete the query: wait for s/e too.
    Never retry a timed-out query automatically (the first query may clear data).
    """
    def __init__(self, send, timeout=5.0):
        self.send = send
        self.timeout = timeout
        self.pending = False
        self.ready = False
        self.deadline = None

    def dispatch(self, now):
        if self.pending and self.ready and self.deadline is None:
            self.send(ccdi_packet('q', '1'))
            self.pending = False
            self.ready = False
            self.deadline = now + self.timeout

    def prompt(self, now):
        self.ready = True
        self.dispatch(now)

    def record(self, ident, text, now):
        sdm_ring = ident == 'r' and parse_ring(text)['call_type'] == '4'
        if (ident == 'p' and text == '1E1') or sdm_ring:
            logging.info('%s received; queued buffered-data query', 'SDM RING' if sdm_ring else 'GPS SDM')
            self.pending = True
            # Wait for the prompt following this notification.
            self.ready = False
        elif ident in ('s', 'e'):
            if self.deadline is not None:
                self.deadline = None
                self.ready = False
            if ident == 'e':
                logging.warning('Radio returned CCDI error: %s', text)
            elif not text:
                logging.warning('Radio SDM buffer is empty')
            else:
                logging.info('Retrieved SDM payload: %r', text)

    def tick(self, now):
        if self.deadline is not None and now >= self.deadline:
            logging.warning('SDM query timed out; no automatic retry. Check capture and radio configuration.')
            self.deadline = None
            self.pending = False
            self.ready = False


def payload(line):
    as_text = isinstance(line, str)
    data = line.encode('ascii') if as_text else line
    data = data.lstrip(b'.')
    if data.startswith(b'$'):
        return data.decode('ascii') if as_text else data
    if len(data) < 5 or not re.fullmatch(b'[a-z][0-9A-Fa-f]{2}', data[:3]):
        raise ValueError('Invalid CCDI header')
    size = int(data[1:3], 16)
    if len(data) != size + 5:
        raise ValueError('CCDI length mismatch')
    if not re.fullmatch(b'[0-9A-Fa-f]{2}', data[-2:]):
        raise ValueError('Invalid CCDI checksum field')
    if (-sum(data[:-2])) & 255 != int(data[-2:], 16):
        raise ValueError('CCDI checksum mismatch')
    result = data[3:-2]
    return result.decode('ascii') if as_text else result


class FrameReader:
    """Use CCDI length, not payload delimiters, to frame binary SDMs."""
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, chunk):
        if not self.buffer and chunk in (b'\r', b'\n'):
            return None
        if not self.buffer and chunk == b'.':
            return 'prompt', chunk
        self.buffer.extend(chunk)
        data = bytes(self.buffer)
        if data.startswith(b'$'):
            if chunk in (b'\r', b'\n'):
                self.buffer.clear()
                return 'record', data[:-1]
        elif len(data) >= 3:
            if not re.fullmatch(b'[a-z][0-9A-Fa-f]{2}', data[:3]):
                self.buffer.clear()
                raise ValueError(f'Invalid CCDI header: {data!r}')
            end = int(data[1:3], 16) + 5
            if len(data) == end + 1:
                self.buffer.clear()
                if chunk != b'\r':
                    raise ValueError('Missing CCDI CR terminator')
                return 'record', data[:-1]
        if len(data) > 4096:
            self.buffer.clear()
            raise ValueError('Oversized record discarded')
        return None


def bcd(value, digits):
    text = f'{value:0{digits}X}'
    if len(text) != digits or not text.isdecimal():
        raise ValueError('Invalid AVL BCD field')
    return int(text)


def parse_avl(data, received=None):
    """Decode TN-856-AN section 8. Month/year are inferred near reception."""
    if len(data) not in (3, 17) or data[0] & 0xF0 != 0x80:
        raise ValueError('Unsupported binary AVL format')
    suffix = f'{bcd(int.from_bytes(data[1:3], "big"), 4):04d}'
    status = data[0] & 3
    if status:
        logging.warning('Radio suffix %s: %s; no point saved', suffix,
                        {1: 'no GPS fix (old data)', 2: 'GPS not operational', 3: 'GPS format error'}[status])
        return None, None
    if len(data) != 17:
        raise ValueError('Truncated successful AVL report')
    if (any(not data[i] & 0x80 for i in (3, 4, 5, 6))
            or not data[7] & 8 or not data[11] & 8
            or data[10] & 0xE0 != 0xA0 or data[14] & 0xC0 != 0x80):
        raise ValueError('Invalid AVL fixed bits')
    hour, minute, second = (bcd(data[i] & 0x7F, 2) for i in (3, 4, 5))
    lat_deg = bcd(((data[6] & 15) << 4) | (data[7] >> 4), 2)
    lat_min = bcd(((data[7] & 7) << 4) | (data[8] >> 4), 2)
    lat_frac = bcd(((data[8] & 15) << 8) | data[9], 3)
    lon_deg = bcd(((data[10] & 31) << 4) | (data[11] >> 4), 3)
    lon_min = bcd(((data[11] & 7) << 4) | (data[12] >> 4), 2)
    lon_frac = bcd(((data[12] & 15) << 8) | data[13], 3)
    lat = coordinate(f'{lat_deg:02d}{lat_min:02d}.{lat_frac:03d}', 'S' if data[6] & 16 else 'N', True)
    lon = coordinate(f'{lon_deg:03d}{lon_min:02d}.{lon_frac:03d}', 'W' if data[6] & 32 else 'E', False)
    day = bcd(data[14] & 63, 2)
    speed = bcd(int.from_bytes(data[15:17], 'big'), 4) / 10
    received = received or datetime.now(timezone.utc)
    candidates = []
    for offset in (-1, 0, 1):
        month_index = received.year * 12 + received.month - 1 + offset
        year, month = divmod(month_index, 12)
        try:
            candidates.append(datetime(year, month + 1, day, hour, minute, second, tzinfo=timezone.utc))
        except ValueError:
            pass
    if not candidates:
        raise ValueError('Invalid AVL day/time')
    when = min(candidates, key=lambda dt: abs((dt - received).total_seconds()))
    details = (f'Radio ID suffix: {suffix} (last four digits only); speed: {speed:.1f} knots; '
               f'GPS day/time UTC; month/year inferred from reception/reference date. '
               f'Emergency: {bool(data[0] & 4)}; alarm: {bool(data[0] & 8)}')
    logging.info('Decoded AVL suffix %s: %s, %.6f, %.6f', suffix, when.isoformat(), lat, lon)
    return (when, lat, lon, None), details


def coordinate(value, hemisphere, latitude):
    if hemisphere not in ('NS' if latitude else 'EW') or len(hemisphere) != 1:
        raise ValueError('Invalid hemisphere')
    digits = 2 if latitude else 3
    if not re.fullmatch(r'\d{' + str(digits + 2) + r'}(?:\.\d+)?', value):
        raise ValueError('Invalid NMEA coordinate')
    degrees, minutes = int(value[:digits]), float(value[digits:])
    limit = 90 if latitude else 180
    if minutes >= 60 or degrees > limit or (degrees == limit and minutes != 0):
        raise ValueError('Coordinate out of range')
    result = degrees + minutes / 60
    return -result if hemisphere in 'SW' else result


def parse_dms(data, received=None):
    """Parse the TP9355 direct-send location text (single-byte degree symbol)."""
    text = data.decode('latin-1')
    pattern = (r'\s*([NS])\s*(\d{1,2})\s*°\s*(\d{1,2})\s*\x27\s*'
               r'(\d{1,2}(?:\.\d+)?)\s*"\s*([EW])\s*(\d{1,3})\s*°\s*'
               r'(\d{1,2})\s*\x27\s*(\d{1,2}(?:\.\d+)?)\s*"\s*')
    match = re.fullmatch(pattern, text)
    if not match:
        return None
    lat_hemi, lat_d, lat_m, lat_s, lon_hemi, lon_d, lon_m, lon_s = match.groups()
    def convert(degrees, minutes, seconds, hemisphere, latitude):
        degrees, minutes, seconds = int(degrees), int(minutes), float(seconds)
        limit = 90 if latitude else 180
        if minutes >= 60 or seconds >= 60 or degrees > limit or (degrees == limit and (minutes or seconds)):
            raise ValueError('DMS coordinate out of range')
        value = degrees + minutes / 60 + seconds / 3600
        return -value if hemisphere in 'SW' else value
    lat = convert(lat_d, lat_m, lat_s, lat_hemi, True)
    lon = convert(lon_d, lon_m, lon_s, lon_hemi, False)
    return received or datetime.now(timezone.utc), lat, lon, None


class SdmSource:
    """Correlate direct-send text with the RING in its receive cycle.

    Never carry an identity across a new RF receive cycle or GPS notification.
    An SDM consumes the association even if its contents are unsupported.
    """
    def __init__(self):
        self.caller = None
        self.deadline = 0

    def record(self, ident, data, now):
        if ident == 'r':
            ring = parse_ring(data.decode('ascii'))
            address = ring['address']
            self.caller = address if ring['category'] == '5' and ring['call_type'] == '4' and address.isdecimal() else None
            self.deadline = now + 5
        elif ident == 'p' and data in (b'05', b'1E1'):
            self.caller = None
        elif ident == 'e':
            self.caller = None
        elif ident == 's':
            caller = self.caller if now <= self.deadline else None
            self.caller = None
            return caller
        return None


def parse_fix(text, received=None):
    """Return (UTC time, latitude, longitude, altitude) or None.

    GGA has no date: use reception time, rather than inventing a GPS date.
    RMC supplies its own UTC date and time. Missing NMEA checksums are rejected.
    """
    match = re.search(r'\$([A-Z]{2}(?:RMC|GGA),[^$*\r\n]*)\*([0-9A-Fa-f]{2})', text)
    if not match:
        return None
    body, checksum = match.groups()
    actual = 0
    for char in body:
        actual ^= ord(char)
    if actual != int(checksum, 16):
        raise ValueError('NMEA checksum mismatch')
    f = body.split(',')
    when = received or datetime.now(timezone.utc)
    altitude = None
    if f[0].endswith('RMC'):
        if len(f) < 10:
            raise ValueError('Truncated RMC')
        if f[2] != 'A' or (len(f) > 12 and f[12] == 'N'):
            return None
        lat, lon = coordinate(f[3], f[4], True), coordinate(f[5], f[6], False)
        when = datetime.strptime(f[9] + f[1], '%d%m%y%H%M%S.%f' if '.' in f[1] else '%d%m%y%H%M%S').replace(tzinfo=timezone.utc)
    else:
        if len(f) < 11:
            raise ValueError('Truncated GGA')
        if int(f[6]) == 0:
            return None
        lat, lon = coordinate(f[2], f[3], True), coordinate(f[4], f[5], False)
        if f[9] and f[10] == 'M':
            altitude = float(f[9])
            if not math.isfinite(altitude):
                raise ValueError('Invalid altitude')
    return when, lat, lon, altitude


def read_kml(path):
    """Validate before opening serial/log files; preserve existing XML content."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f'Cannot append to malformed KML: {exc}') from exc
    ns = '{http://www.opengis.net/kml/2.2}'
    if root.tag != ns + 'kml' or len(root.findall(ns + 'Document')) != 1:
        raise ValueError('Append requires a KML 2.2 file with one top-level Document')
    return root


def write_kml(path, fixes, name, descriptions=None, existing=None, radio_ids=None):
    """Atomic replacement keeps the previous complete file on interrupted writes."""
    namespace = 'http://www.opengis.net/kml/2.2'
    ET.register_namespace('', namespace)
    def element(parent, tag, value=None):
        item = ET.SubElement(parent, '{' + namespace + '}' + tag)
        if value is not None:
            item.text = str(value)
        return item
    if existing is None:
        root = ET.Element('{' + namespace + '}kml')
        doc = element(root, 'Document')
        element(doc, 'name', name)
    else:
        # Each update starts from the original snapshot, so session points
        # are written once. Keep previous tracks and metadata intact.
        root = copy.deepcopy(existing)
        document = root.find('{' + namespace + '}Document')
        doc = element(document, 'Folder')
        element(doc, 'name', name)
    tracks = {}
    for index, fix in enumerate(fixes):
        key = radio_ids[index] if radio_ids else None
        tracks.setdefault(key, []).append(fix)
    for radio_id, points in tracks.items():
        if len(points) < 2:
            continue
        mark = element(doc, 'Placemark')
        element(mark, 'name', radio_id or 'Unknown radio')
        track = element(mark, 'LineString')
        element(track, 'tessellate', '1')
        element(track, 'altitudeMode', 'clampToGround')
        element(track, 'coordinates', ' '.join(f'{lon:.8f},{lat:.8f},0' for _, lat, lon, _ in points))
    for index, (when, lat, lon, altitude) in enumerate(fixes):
        mark = element(doc, 'Placemark')
        radio_id = radio_ids[index] if radio_ids else None
        element(mark, 'name', radio_id or 'Unknown radio')
        element(element(mark, 'TimeStamp'), 'when', when.isoformat().replace('+00:00', 'Z'))
        if descriptions and descriptions[index]:
            element(mark, 'description', descriptions[index])
        elif altitude is not None:
            element(mark, 'description', f'GPS altitude: {altitude} m')
        point = element(mark, 'Point')
        element(point, 'coordinates', f'{lon:.8f},{lat:.8f},0')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as handle:
            temporary = handle.name
            ET.ElementTree(root).write(handle, encoding='utf-8', xml_declaration=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--port', help='Serial port, e.g. COM3 or /dev/ttyUSB0')
    source.add_argument('--input', type=Path, help='Replay a raw serial capture')
    parser.add_argument('--baud', type=int, default=9600)
    parser.add_argument('--flow-control', choices=['none', 'xonxoff', 'rtscts'], default='none')
    parser.add_argument('--output', type=Path, default=Path('locations.kml'))
    parser.add_argument('--append', action='store_true', help='Preserve existing KML and add this session in a new folder')
    parser.add_argument('--raw-log', type=Path, help='Append received bytes for diagnosis/replay')
    parser.add_argument('--event-log', type=Path, help='Append timestamped RX records and TX commands')
    parser.add_argument('--passive', action='store_true', help='Disable automatic SDM retrieval')
    parser.add_argument('--reference-date', type=lambda value: datetime.strptime(value, '%Y-%m-%d').replace(tzinfo=timezone.utc),
                        help='UTC reference date for replaying AVL day/time, e.g. 2026-10-29')
    parser.add_argument('--name', default='TAIT GPS track')
    parser.add_argument('--verbose', action='store_true', help='Show received records for protocol diagnosis')
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(levelname)s: %(message)s')
    if args.output.exists() and not args.append:
        parser.error('Output already exists; use --append or choose a new --output filename')
    paths = [args.output, args.input, args.raw_log, args.event_log]
    resolved = [p.resolve() for p in paths if p is not None]
    if len(set(resolved)) != len(resolved):
        parser.error('Input, output and log files must be different files')
    if args.baud <= 0:
        parser.error('--baud must be positive')
    if args.reference_date and args.port:
        parser.error('--reference-date is for capture replay; live logging uses reception UTC')
    fixes = []
    descriptions = []
    radio_ids = []
    try:
        existing = read_kml(args.output) if args.append and args.output.exists() else None
        if existing is not None:
            logging.info('Appending a new session to %s', args.output)
        if args.port:
            try:
                import serial
            except ImportError:
                parser.error('Install pyserial: python -m pip install -r requirements.txt')
            stream = serial.Serial(args.port, args.baud, timeout=0.5,
                                   write_timeout=2,
                                   xonxoff=args.flow_control == 'xonxoff',
                                   rtscts=args.flow_control == 'rtscts')
        else:
            stream = args.input.open('rb')
        with stream:
            raw = args.raw_log.open('ab') if args.raw_log else None
            events = None
            try:
                events = args.event_log.open('a', encoding='utf-8') if args.event_log else None
                def event(direction, data):
                    if events:
                        events.write(f'{datetime.now(timezone.utc).isoformat()} {direction} {data!r}\n')
                        events.flush()

                def send(command):
                    if stream.write(command) != len(command):
                        raise OSError('Incomplete serial command write')
                    event('TX', command)
                    logging.info('TX %r', command)

                retrieval = SdmRetrieval(send) if args.port and not args.passive else None
                if existing is None:
                    write_kml(args.output, fixes, args.name)
                reader = FrameReader()
                source_context = SdmSource()
                while True:
                    chunk = stream.read(1)
                    if retrieval:
                        retrieval.tick(time.monotonic())
                    if not chunk:
                        if args.input:
                            if reader.buffer:
                                logging.warning('Ignored unterminated final record')
                            break
                        continue
                    if raw:
                        raw.write(chunk)
                        raw.flush()
                    try:
                        framed = reader.feed(chunk)
                    except ValueError as exc:
                        logging.warning('Framing error: %s', exc)
                        continue
                    if framed is None:
                        continue
                    kind, line = framed
                    if kind == 'prompt':
                        event('RX', line)
                        if retrieval:
                            retrieval.prompt(time.monotonic())
                        continue
                    if kind == 'record':
                        logging.debug('RX %r', line)
                        event('RX', line)
                        try:
                            data = payload(line)
                            ident = chr(line[0])
                            caller = source_context.record(ident, data, time.monotonic())
                            if ident == 'r':
                                ring = parse_ring(data.decode('ascii'))
                                logging.info('RING: %s, category %s, caller/address %s',
                                             'SDM received' if ring['call_type'] == '4' else f"call type {ring['call_type']}",
                                             ring['category'], ring['address'])
                            if retrieval:
                                # Complete valid binary responses before attempting GPS decoding.
                                retrieval.record(ident, data if ident == 's' else data.decode('ascii'), time.monotonic())
                            if ident == 'p':
                                status = {'05': 'Receiver busy', '06': 'Receiver not busy',
                                          '1E1': 'GPS SDM received'}.get(data.decode('ascii'), 'Radio progress')
                                logging.debug('%s (%r)', status, data)
                                continue
                            if ident == 'r':
                                continue
                            if ident == 'e':
                                if not retrieval:
                                    logging.warning('Radio returned CCDI error: %r', data)
                                continue
                            description = None
                            radio_id = None
                            if ident == 's' and data and data[0] & 0x80:
                                fix, description = parse_avl(data, args.reference_date)
                                if fix:
                                    radio_id = f'{bcd(int.from_bytes(data[1:3], "big"), 4):04d}'
                            else:
                                fix = parse_dms(data, args.reference_date) if ident == 's' else None
                                if fix:
                                    radio_id = caller
                                    description = ('Direct-send DMS location; timestamp is reception/reference UTC '
                                                   '(message has no GPS date/time). '
                                                   + (f'Caller ID: {caller} from preceding DMR SDM RING.' if caller else 'Caller ID unavailable.'))
                                else:
                                    # ASCII decoding is only required for an actual NMEA sentence.
                                    fix = parse_fix(data.decode('ascii'), args.reference_date) if b'$' in data else None
                            if fix:
                                fixes.append(fix)
                                descriptions.append(description)
                                radio_ids.append(radio_id)
                                write_kml(args.output, fixes, args.name, descriptions, existing, radio_ids)
                                logging.info('Saved %d fixes: %.6f, %.6f', len(fixes), fix[1], fix[2])
                            elif data:
                                if ident == 's':
                                    logging.warning('SDM has no supported current fix; preserve capture for diagnosis')
                                logging.debug('No supported location in %r', data)
                        except (ValueError, UnicodeError) as exc:
                            logging.warning('Ignored record: %s', exc)
            finally:
                if raw:
                    raw.close()
                if events:
                    events.close()
    except KeyboardInterrupt:
        logging.info('Stopped; saved %d fixes in %s', len(fixes), args.output)
    except (OSError, ValueError) as exc:
        logging.error('%s', exc)
        return 1
    if not fixes:
        logging.warning('No supported GPS fixes saved. Check serial settings and inspect the raw capture.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
