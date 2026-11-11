export const WINDOWS = [0, 5, 15, 30, 60, 180, 360, 720, 1440, 4320, 10080, Infinity];
export function customRadioName(value) { return typeof value === 'string' ? value.trim().replace(/\s+/g, ' ').slice(0, 40) : ''; }
export function radioName(id, aliases) { return customRadioName(aliases.get(String(id))) || String(id); }
export const COORDINATE_FORMATS = ['latlon', 'mgrs3', 'mgrs4', 'mgrs5'];
export function coordinateText(lat, lon, format = 'latlon') {
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return 'Coordinates unavailable';
  const decimal = `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
  if (!COORDINATE_FORMATS.includes(format) || format === 'latlon') return decimal;
  if (lat < -80 || lat > 84) return `MGRS unavailable in polar regions · ${decimal}`;
  const grid = mgrsEngine.forward([lon, lat], Number(format.at(-1)));
  const match = grid.match(/^(\d{1,2}[A-Z])([A-Z]{2})(\d+)$/);
  if (!match) return `MGRS unavailable · ${decimal}`;
  const half = match[3].length / 2;
  return `MGRS ${match[1]} ${match[2]} ${match[3].slice(0, half)} ${match[3].slice(half)}`;
}
export const COLORS = ['#168570', '#db7044', '#6c67c7', '#277cb1', '#bd5084', '#a07a23', '#398458', '#875e46'];
export const MAP_STYLES = {
  standard:{label:'OpenStreetMap Standard',url:'https://tile.openstreetmap.org/{z}/{x}/{y}.png'},
  humanitarian:{label:'OpenStreetMap Humanitarian',url:'https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png',extra:' · Tiles © <a href="https://www.openstreetmap.fr/">OSM France</a>, style <a href="https://www.hotosm.org/">HOT</a>'},
  topographic:{label:'OpenTopoMap',url:'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',maxNativeZoom:17,extra:' · Map © <a href="https://opentopomap.org/">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>), elevation SRTM'},
  greyscale:{label:'OpenStreetMap Greyscale',url:'https://tile.openstreetmap.org/{z}/{x}/{y}.png',filter:'greyscale'},
  dark:{label:'OpenStreetMap Dark (filtered)',url:'https://tile.openstreetmap.org/{z}/{x}/{y}.png',filter:'dark'}
};
export function mapStyle(value) { return Object.hasOwn(MAP_STYLES, value) ? value : 'standard'; }
export function mapName(value) { return String(value ?? '').trim().replace(/\s+/g, ' ').slice(0, 40) || 'TAIT'; }
export function afterClear(points, cutoff) {
  return cutoff === null ? points : points.filter(point => Date.parse(point.time) > cutoff);
}
export function windowLabel(minutes) {
  if (minutes === 0) return 'Latest positions only';
  if (!Number.isFinite(minutes)) return 'All recorded history';
  if (minutes < 60) return `${minutes} minutes`;
  if (minutes < 1440) return `${minutes / 60} hour${minutes === 60 ? '' : 's'}`;
  return `${minutes / 1440} day${minutes === 1440 ? '' : 's'}`;
}
export function colorFor(id) {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return COLORS[hash % COLORS.length];
}
export function normalize(points) {
  const radios = new Map();
  const seen = new Set();
  for (const p of points) {
    const time = Date.parse(p.time), lat = Number(p.lat), lon = Number(p.lon);
    if (!Number.isFinite(time) || !Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) continue;
    const id = String(p.id || 'Unknown radio');
    const key = JSON.stringify([id, time, lat, lon]);
    if (seen.has(key)) continue;
    seen.add(key);
    if (!radios.has(id)) radios.set(id, { id, color: colorFor(id), points: [] });
    radios.get(id).points.push({ ...p, id, lat, lon, time, session: p.session || 'default' });
  }
  for (const radio of radios.values()) {
    radio.points.sort((a, b) => a.time - b.time);
    radio.latest = radio.points.at(-1);
  }
  return [...radios.values()].sort((a, b) => a.id.localeCompare(b.id, undefined, {numeric: true}));
}
export function historyPoints(radio, minutes, anchor) {
  if (minutes === 0) return [];
  const cutoff = anchor - minutes * 60000;
  return radio.points.filter(point => point.time >= cutoff);
}
export function trailSegments(radio, minutes, anchor) {
  const sessions = new Map();
  for (const point of historyPoints(radio, minutes, anchor)) {
    if (!sessions.has(point.session)) sessions.set(point.session, []);
    sessions.get(point.session).push(point);
  }
  return [...sessions.values()].filter(points => points.length > 1);
}
export function parseKml(text, filename = 'Uploaded KML') {
  const doc = new DOMParser().parseFromString(text, 'application/xml');
  if (doc.getElementsByTagName('parsererror').length || doc.documentElement.localName !== 'kml') throw new Error(`${filename}: invalid KML file`);
  const descendants = (el, name) => [...el.getElementsByTagNameNS('*', name)];
  const value = (el, name) => descendants(el, name)[0]?.textContent?.trim() || '';
  const folders = descendants(doc, 'Folder');
  const points = [];
  for (const mark of descendants(doc, 'Placemark')) {
    const point = descendants(mark, 'Point')[0];
    const time = value(mark, 'when');
    if (!point || !time || !/(?:Z|[+-]\d{2}:\d{2})$/.test(time)) continue;
    const coordinates = value(point, 'coordinates').split(',');
    if (coordinates.length < 2 || coordinates.slice(0, 2).some(n => !n.trim())) continue;
    const [lon, lat] = coordinates.map(Number);
    const name = value(mark, 'name'), description = value(mark, 'description');
    const identity = description.match(/(?:Radio ID suffix:|Caller ID:)\s*(\d+)/);
    const id = /^\d+$/.test(name) ? name : identity?.[1] || 'Unknown radio';
    let parent = mark.parentElement;
    while (parent && parent.localName !== 'Folder') parent = parent.parentElement;
    points.push({id, lat, lon, time, description, session: `${filename}:${parent ? folders.indexOf(parent) : 'root'}`});
  }
  return points;
}

// Bundled proj4js/mgrs 2.1.0; see vendor/mgrs-license.md and mgrs-openmap-license.md.
const mgrsEngine = (() => {
/**
 * UTM zones are grouped, and assigned to one of a group of 6
 * sets.
 *
 * {int} @private
 */
const NUM_100K_SETS = 6;

/**
 * The column letters (for easting) of the lower left value, per
 * set.
 *
 * {string} @private
 */
const SET_ORIGIN_COLUMN_LETTERS = 'AJSAJS';

/**
 * The row letters (for northing) of the lower left value, per
 * set.
 *
 * {string} @private
 */
const SET_ORIGIN_ROW_LETTERS = 'AFAFAF';

const A = 65; // A
const I = 73; // I
const O = 79; // O
const V = 86; // V
const Z = 90; // Z

/**
 * First eccentricity squared
 * {number} @private
 */
const ECC_SQUARED = 0.00669438;

/**
 * Scale factor along the central meridian
 * {number} @private
 */
const SCALE_FACTOR = 0.9996;

/**
 * Semimajor axis (half the width of the earth) in meters
 * {number} @private
 */
const SEMI_MAJOR_AXIS = 6378137;

/**
 * The easting of the central meridian of each UTM zone
 * {number} @private
 */
const EASTING_OFFSET = 500000;

/**
 * The northing of the equator for southern hemisphere locations (in UTM)
 * {number} @private
 */
const NORTHING_OFFFSET = 10000000;

/**
 * UTM zone width in degrees
 * {number} private
 */
const UTM_ZONE_WIDTH = 6;

/**
 * Half the width of a UTM zone in degrees
 * {number} private
 */
const HALF_UTM_ZONE_WIDTH = UTM_ZONE_WIDTH / 2;

/**
 * Convert lat/lon to MGRS.
 *
 * @param {[number, number]} ll Array with longitude and latitude on a
 *     WGS84 ellipsoid.
 * @param {number} [accuracy=5] Accuracy in digits (5 for 1 m, 4 for 10 m, 3 for
 *      100 m, 2 for 1 km, 1 for 10 km or 0 for 100 km). Optional, default is 5.
 * @return {string} the MGRS string for the given location and accuracy.
 */
function forward(ll, accuracy) {
  accuracy = typeof accuracy === 'number' ? accuracy : 5; // default accuracy 1m

  if (!Array.isArray(ll)) {
    throw new TypeError('forward did not receive an array');
  }

  if (typeof ll[0] === 'string' || typeof ll[1] === 'string') {
    throw new TypeError('forward received an array of strings, but it only accepts an array of numbers.');
  }

  const [ lon, lat ] = ll;
  if (lon < -180 || lon > 180) {
    throw new TypeError(`forward received an invalid longitude of ${lon}`);
  }
  if (lat < -90 || lat > 90) {
    throw new TypeError(`forward received an invalid latitude of ${lat}`);
  }

  if (lat < -80 || lat > 84) {
    throw new TypeError(`forward received a latitude of ${lat}, but this library does not support conversions of points in polar regions below 80°S and above 84°N`);
  }

  return encode(LLtoUTM({ lat, lon }), accuracy);
}

/**
 * Convert MGRS to lat/lon bounding box.
 *
 * @param {string} mgrs MGRS string.
 * @return {[number,number,number,number]} An array with left (longitude),
 *    bottom (latitude), right
 *    (longitude) and top (latitude) values in WGS84, representing the
 *    bounding box for the provided MGRS reference.
 */
function inverse(mgrs) {
  const bbox = UTMtoLL(decode(mgrs.toUpperCase()));
  if (typeof bbox.lat === 'number' && typeof bbox.lon === 'number') {
    return [bbox.lon, bbox.lat, bbox.lon, bbox.lat];
  }
  return [bbox.left, bbox.bottom, bbox.right, bbox.top];
}

function toPoint(mgrs) {
  if (mgrs === '') {
    throw new TypeError('toPoint received a blank string');
  }
  const bbox = UTMtoLL(decode(mgrs.toUpperCase()));
  if (typeof bbox.lat === 'number' && typeof bbox.lon === 'number') {
    return [bbox.lon, bbox.lat];
  }
  return [(bbox.left + bbox.right) / 2, (bbox.top + bbox.bottom) / 2];
}

/**
 * Conversion from degrees to radians.
 *
 * @private
 * @param {number} deg the angle in degrees.
 * @return {number} the angle in radians.
 */
function degToRad(deg) {
  return (deg * (Math.PI / 180));
}

/**
 * Conversion from radians to degrees.
 *
 * @private
 * @param {number} rad the angle in radians.
 * @return {number} the angle in degrees.
 */
function radToDeg(rad) {
  return (180 * (rad / Math.PI));
}

/**
 * Converts a set of Longitude and Latitude co-ordinates to UTM
 * using the WGS84 ellipsoid.
 *
 * @private
 * @param {object} ll Object literal with lat and lon properties
 *     representing the WGS84 coordinate to be converted.
 * @return {object} Object literal containing the UTM value with easting,
 *     northing, zoneNumber and zoneLetter properties, and an optional
 *     accuracy property in digits. Returns null if the conversion failed.
 */
function LLtoUTM(ll) {
  const Lat = ll.lat;
  const Long = ll.lon;
  const a = SEMI_MAJOR_AXIS;
  const LatRad = degToRad(Lat);
  const LongRad = degToRad(Long);
  let ZoneNumber;
  // (int)
  ZoneNumber = Math.floor((Long + 180) / 6) + 1;

  //Make sure the longitude 180 is in Zone 60
  if (Long === 180) {
    ZoneNumber = 60;
  }

  // Special zone for Norway
  if (Lat >= 56 && Lat < 64 && Long >= 3 && Long < 12) {
    ZoneNumber = 32;
  }

  // Special zones for Svalbard
  if (Lat >= 72 && Lat < 84) {
    if (Long >= 0 && Long < 9) {
      ZoneNumber = 31;
    }
    else if (Long >= 9 && Long < 21) {
      ZoneNumber = 33;
    }
    else if (Long >= 21 && Long < 33) {
      ZoneNumber = 35;
    }
    else if (Long >= 33 && Long < 42) {
      ZoneNumber = 37;
    }
  }

  // +HALF_UTM_ZONE_WIDTH puts origin in middle of zone
  const LongOrigin = (ZoneNumber - 1) * UTM_ZONE_WIDTH - 180 + HALF_UTM_ZONE_WIDTH;

  const LongOriginRad = degToRad(LongOrigin);

  const eccPrimeSquared = (ECC_SQUARED) / (1 - ECC_SQUARED);

  const N = a / Math.sqrt(1 - ECC_SQUARED * Math.sin(LatRad) * Math.sin(LatRad));
  const T = Math.tan(LatRad) * Math.tan(LatRad);
  const C = eccPrimeSquared * Math.cos(LatRad) * Math.cos(LatRad);
  const A = Math.cos(LatRad) * (LongRad - LongOriginRad);

  const M = a * ((1 - ECC_SQUARED / 4 - 3 * ECC_SQUARED * ECC_SQUARED / 64 - 5 * ECC_SQUARED * ECC_SQUARED * ECC_SQUARED / 256) * LatRad - (3 * ECC_SQUARED / 8 + 3 * ECC_SQUARED * ECC_SQUARED / 32 + 45 * ECC_SQUARED * ECC_SQUARED * ECC_SQUARED / 1024) * Math.sin(2 * LatRad) + (15 * ECC_SQUARED * ECC_SQUARED / 256 + 45 * ECC_SQUARED * ECC_SQUARED * ECC_SQUARED / 1024) * Math.sin(4 * LatRad) - (35 * ECC_SQUARED * ECC_SQUARED * ECC_SQUARED / 3072) * Math.sin(6 * LatRad));

  const UTMEasting = (SCALE_FACTOR * N * (A + (1 - T + C) * A * A * A / 6 + (5 - 18 * T + T * T + 72 * C - 58 * eccPrimeSquared) * A * A * A * A * A / 120) + EASTING_OFFSET);

  let UTMNorthing = (SCALE_FACTOR * (M + N * Math.tan(LatRad) * (A * A / 2 + (5 - T + 9 * C + 4 * C * C) * A * A * A * A / 24 + (61 - 58 * T + T * T + 600 * C - 330 * eccPrimeSquared) * A * A * A * A * A * A / 720)));
  if (Lat < 0) {
    UTMNorthing += NORTHING_OFFFSET;
  }

  return {
    northing: Math.trunc(UTMNorthing),
    easting: Math.trunc(UTMEasting),
    zoneNumber: ZoneNumber,
    zoneLetter: getLetterDesignator(Lat)
  };
}

/**
 * Converts UTM coords to lat/long, using the WGS84 ellipsoid. This is a convenience
 * class where the Zone can be specified as a single string eg."60N" which
 * is then broken down into the ZoneNumber and ZoneLetter.
 *
 * @private
 * @param {object} utm An object literal with northing, easting, zoneNumber
 *     and zoneLetter properties. If an optional accuracy property is
 *     provided (in meters), a bounding box will be returned instead of
 *     latitude and longitude.
 * @return {object} An object literal containing either lat and lon values
 *     (if no accuracy was provided), or top, right, bottom and left values
 *     for the bounding box calculated according to the provided accuracy.
 *     Returns null if the conversion failed.
 */
function UTMtoLL(utm) {

  const UTMNorthing = utm.northing;
  const UTMEasting = utm.easting;
  const { zoneLetter, zoneNumber } = utm;
  // check the ZoneNummber is valid
  if (zoneNumber < 0 || zoneNumber > 60) {
    return null;
  }

  const a = SEMI_MAJOR_AXIS;
  const e1 = (1 - Math.sqrt(1 - ECC_SQUARED)) / (1 + Math.sqrt(1 - ECC_SQUARED));

  // remove 500,000 meter offset for longitude
  const x = UTMEasting - EASTING_OFFSET;
  let y = UTMNorthing;

  // We must know somehow if we are in the Northern or Southern
  // hemisphere, this is the only time we use the letter So even
  // if the Zone letter isn't exactly correct it should indicate
  // the hemisphere correctly
  if (zoneLetter < 'N') {
    y -= NORTHING_OFFFSET; // remove offset used for southern hemisphere
  }

  // +HALF_UTM_ZONE_WIDTH puts origin in middle of zone
  const LongOrigin = (zoneNumber - 1) * UTM_ZONE_WIDTH - 180 + HALF_UTM_ZONE_WIDTH;

  const eccPrimeSquared = (ECC_SQUARED) / (1 - ECC_SQUARED);

  const M = y / SCALE_FACTOR;
  const mu = M / (a * (1 - ECC_SQUARED / 4 - 3 * ECC_SQUARED * ECC_SQUARED / 64 - 5 * ECC_SQUARED * ECC_SQUARED * ECC_SQUARED / 256));

  const phi1Rad = mu + (3 * e1 / 2 - 27 * e1 * e1 * e1 / 32) * Math.sin(2 * mu) + (21 * e1 * e1 / 16 - 55 * e1 * e1 * e1 * e1 / 32) * Math.sin(4 * mu) + (151 * e1 * e1 * e1 / 96) * Math.sin(6 * mu);
  // double phi1 = ProjMath.radToDeg(phi1Rad);

  const N1 = a / Math.sqrt(1 - ECC_SQUARED * Math.sin(phi1Rad) * Math.sin(phi1Rad));
  const T1 = Math.tan(phi1Rad) * Math.tan(phi1Rad);
  const C1 = eccPrimeSquared * Math.cos(phi1Rad) * Math.cos(phi1Rad);
  const R1 = a * (1 - ECC_SQUARED) / Math.pow(1 - ECC_SQUARED * Math.sin(phi1Rad) * Math.sin(phi1Rad), 1.5);
  const D = x / (N1 * SCALE_FACTOR);

  let lat = phi1Rad - (N1 * Math.tan(phi1Rad) / R1) * (D * D / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * eccPrimeSquared) * D * D * D * D / 24 + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * eccPrimeSquared - 3 * C1 * C1) * D * D * D * D * D * D / 720);
  lat = radToDeg(lat);

  let lon = (D - (1 + 2 * T1 + C1) * D * D * D / 6 + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * eccPrimeSquared + 24 * T1 * T1) * D * D * D * D * D / 120) / Math.cos(phi1Rad);
  lon = LongOrigin + radToDeg(lon);

  let result;
  if (typeof utm.accuracy === 'number') {
    const topRight = UTMtoLL({
      northing: utm.northing + utm.accuracy,
      easting: utm.easting + utm.accuracy,
      zoneLetter: utm.zoneLetter,
      zoneNumber: utm.zoneNumber
    });
    result = {
      top: topRight.lat,
      right: topRight.lon,
      bottom: lat,
      left: lon
    };
  }
  else {
    result = {
      lat,
      lon
    };
  }
  return result;
}

/**
 * Calculates the MGRS letter designator for the given latitude.
 *
 * @private (Not intended for public API, only exported for testing.)
 * @param {number} latitude The latitude in WGS84 to get the letter designator
 *     for.
 * @return {string} The letter designator.
 */
function getLetterDesignator(latitude) {
  if (latitude <= 84 && latitude >= 72) {
    // the X band is 12 degrees high
    return 'X';
  } else if (latitude < 72 && latitude >= -80) {
    // Latitude bands are lettered C through X, excluding I and O
    const bandLetters = 'CDEFGHJKLMNPQRSTUVWX';
    const bandHeight = 8;
    const minLatitude = -80;
    const index = Math.floor((latitude - minLatitude) / bandHeight);
    return bandLetters[index];
  } else if (latitude > 84 || latitude < -80) {
    //This is here as an error flag to show that the Latitude is
    //outside MGRS limits
    return 'Z';
  }
}

/**
 * Encodes a UTM location as MGRS string.
 *
 * @private
 * @param {object} utm An object literal with easting, northing,
 *     zoneLetter, zoneNumber
 * @param {number} accuracy Accuracy in digits (0-5).
 * @return {string} MGRS string for the given UTM location.
 */
function encode(utm, accuracy) {
  // prepend with leading zeroes
  const seasting = '00000' + utm.easting,
    snorthing = '00000' + utm.northing;

  return utm.zoneNumber + utm.zoneLetter + get100kID(utm.easting, utm.northing, utm.zoneNumber) + seasting.substr(seasting.length - 5, accuracy) + snorthing.substr(snorthing.length - 5, accuracy);
}

/**
 * Get the two letter 100k designator for a given UTM easting,
 * northing and zone number value.
 *
 * @private
 * @param {number} easting
 * @param {number} northing
 * @param {number} zoneNumber
 * @return {string} the two letter 100k designator for the given UTM location.
 */
function get100kID(easting, northing, zoneNumber) {
  const setParm = get100kSetForZone(zoneNumber);
  const setColumn = Math.floor(easting / 100000);
  const setRow = Math.floor(northing / 100000) % 20;
  return getLetter100kID(setColumn, setRow, setParm);
}

/**
 * Given a UTM zone number, figure out the MGRS 100K set it is in.
 *
 * @private
 * @param {number} i An UTM zone number.
 * @return {number} the 100k set the UTM zone is in.
 */
function get100kSetForZone(i) {
  let setParm = i % NUM_100K_SETS;
  if (setParm === 0) {
    setParm = NUM_100K_SETS;
  }

  return setParm;
}

/**
 * Get the two-letter MGRS 100k designator given information
 * translated from the UTM northing, easting and zone number.
 *
 * @private
 * @param {number} column the column index as it relates to the MGRS
 *        100k set spreadsheet, created from the UTM easting.
 *        Values are 1-8.
 * @param {number} row the row index as it relates to the MGRS 100k set
 *        spreadsheet, created from the UTM northing value. Values
 *        are from 0-19.
 * @param {number} parm the set block, as it relates to the MGRS 100k set
 *        spreadsheet, created from the UTM zone. Values are from
 *        1-60.
 * @return {string} two letter MGRS 100k code.
 */
function getLetter100kID(column, row, parm) {
  // colOrigin and rowOrigin are the letters at the origin of the set
  const index = parm - 1;
  const colOrigin = SET_ORIGIN_COLUMN_LETTERS.charCodeAt(index);
  const rowOrigin = SET_ORIGIN_ROW_LETTERS.charCodeAt(index);

  // colInt and rowInt are the letters to build to return
  let colInt = colOrigin + column - 1;
  let rowInt = rowOrigin + row;
  let rollover = false;

  if (colInt > Z) {
    colInt = colInt - Z + A - 1;
    rollover = true;
  }

  if (colInt === I || (colOrigin < I && colInt > I) || ((colInt > I || colOrigin < I) && rollover)) {
    colInt++;
  }

  if (colInt === O || (colOrigin < O && colInt > O) || ((colInt > O || colOrigin < O) && rollover)) {
    colInt++;

    if (colInt === I) {
      colInt++;
    }
  }

  if (colInt > Z) {
    colInt = colInt - Z + A - 1;
  }

  if (rowInt > V) {
    rowInt = rowInt - V + A - 1;
    rollover = true;
  }
  else {
    rollover = false;
  }

  if (((rowInt === I) || ((rowOrigin < I) && (rowInt > I))) || (((rowInt > I) || (rowOrigin < I)) && rollover)) {
    rowInt++;
  }

  if (((rowInt === O) || ((rowOrigin < O) && (rowInt > O))) || (((rowInt > O) || (rowOrigin < O)) && rollover)) {
    rowInt++;

    if (rowInt === I) {
      rowInt++;
    }
  }

  if (rowInt > V) {
    rowInt = rowInt - V + A - 1;
  }

  const twoLetter = String.fromCharCode(colInt) + String.fromCharCode(rowInt);
  return twoLetter;
}

/**
 * Decode the UTM parameters from a MGRS string.
 *
 * @private
 * @param {string} mgrsString an UPPERCASE coordinate string is expected.
 * @return {object} An object literal with easting, northing, zoneLetter,
 *     zoneNumber and accuracy (in meters) properties.
 */
function decode(mgrsString) {

  if (mgrsString && mgrsString.length === 0) {
    throw new TypeError('MGRSPoint coverting from nothing');
  }

  //remove any spaces in MGRS String
  mgrsString = mgrsString.replace(/ /g, '');

  const { length } = mgrsString;

  let hunK = null;
  let sb = '';
  let testChar;
  let i = 0;

  // get Zone number
  while (!(/[A-Z]/).test(testChar = mgrsString.charAt(i))) {
    if (i >= 2) {
      throw new Error(`MGRSPoint bad conversion from: ${mgrsString}`);
    }
    sb += testChar;
    i++;
  }

  const zoneNumber = parseInt(sb, 10);

  if (i === 0 || i + 3 > length) {
    // A good MGRS string has to be 4-5 digits long,
    // ##AAA/#AAA at least.
    throw new Error(`MGRSPoint bad conversion from ${mgrsString}`);
  }

  const zoneLetter = mgrsString.charAt(i++);

  // Should we check the zone letter here? Why not.
  if (zoneLetter <= 'A' || zoneLetter === 'B' || zoneLetter === 'Y' || zoneLetter >= 'Z' || zoneLetter === 'I' || zoneLetter === 'O') {
    throw new Error(`MGRSPoint zone letter ${zoneLetter} not handled: ${mgrsString}`);
  }

  hunK = mgrsString.substring(i, i += 2);

  const set = get100kSetForZone(zoneNumber);

  const east100k = getEastingFromChar(hunK.charAt(0), set);
  let north100k = getNorthingFromChar(hunK.charAt(1), set);

  // We have a bug where the northing may be 2000000 too low.
  // How
  // do we know when to roll over?

  while (north100k < getMinNorthing(zoneLetter)) {
    north100k += 2000000;
  }

  // calculate the char index for easting/northing separator
  const remainder = length - i;

  if (remainder % 2 !== 0) {
    throw new Error(`MGRSPoint has to have an even number
of digits after the zone letter and two 100km letters - front
half for easting meters, second half for
northing meters ${mgrsString}`);
  }

  const sep = remainder / 2;

  let sepEasting = 0;
  let sepNorthing = 0;
  let accuracyBonus, sepEastingString, sepNorthingString;
  if (sep > 0) {
    accuracyBonus = 100000 / Math.pow(10, sep);
    sepEastingString = mgrsString.substring(i, i + sep);
    sepEasting = parseFloat(sepEastingString) * accuracyBonus;
    sepNorthingString = mgrsString.substring(i + sep);
    sepNorthing = parseFloat(sepNorthingString) * accuracyBonus;
  }

  const easting = sepEasting + east100k;
  const northing = sepNorthing + north100k;

  return {
    easting,
    northing,
    zoneLetter,
    zoneNumber,
    accuracy: accuracyBonus
  };
}

/**
 * Given the first letter from a two-letter MGRS 100k zone, and given the
 * MGRS table set for the zone number, figure out the easting value that
 * should be added to the other, secondary easting value.
 *
 * @private
 * @param {string} e The first letter from a two-letter MGRS 100´k zone.
 * @param {number} set The MGRS table set for the zone number.
 * @return {number} The easting value for the given letter and set.
 */
function getEastingFromChar(e, set) {
  // colOrigin is the letter at the origin of the set for the
  // column
  let curCol = SET_ORIGIN_COLUMN_LETTERS.charCodeAt(set - 1);
  let eastingValue = 100000;
  let rewindMarker = false;

  while (curCol !== e.charCodeAt(0)) {
    curCol++;
    if (curCol === I) {
      curCol++;
    }
    if (curCol === O) {
      curCol++;
    }
    if (curCol > Z) {
      if (rewindMarker) {
        throw new Error(`Bad character: ${e}`);
      }
      curCol = A;
      rewindMarker = true;
    }
    eastingValue += 100000;
  }

  return eastingValue;
}

/**
 * Given the second letter from a two-letter MGRS 100k zone, and given the
 * MGRS table set for the zone number, figure out the northing value that
 * should be added to the other, secondary northing value. You have to
 * remember that Northings are determined from the equator, and the vertical
 * cycle of letters mean a 2000000 additional northing meters. This happens
 * approx. every 18 degrees of latitude. This method does *NOT* count any
 * additional northings. You have to figure out how many 2000000 meters need
 * to be added for the zone letter of the MGRS coordinate.
 *
 * @private
 * @param {string} n Second letter of the MGRS 100k zone
 * @param {number} set The MGRS table set number, which is dependent on the
 *     UTM zone number.
 * @return {number} The northing value for the given letter and set.
 */
function getNorthingFromChar(n, set) {

  if (n > 'V') {
    throw new TypeError(`MGRSPoint given invalid Northing ${n}`);
  }

  // rowOrigin is the letter at the origin of the set for the
  // column
  let curRow = SET_ORIGIN_ROW_LETTERS.charCodeAt(set - 1);
  let northingValue = 0;
  let rewindMarker = false;

  while (curRow !== n.charCodeAt(0)) {
    curRow++;
    if (curRow === I) {
      curRow++;
    }
    if (curRow === O) {
      curRow++;
    }
    // fixing a bug making whole application hang in this loop
    // when 'n' is a wrong character
    if (curRow > V) {
      if (rewindMarker) { // making sure that this loop ends
        throw new Error(`Bad character: ${n}`);
      }
      curRow = A;
      rewindMarker = true;
    }
    northingValue += 100000;
  }

  return northingValue;
}

/**
 * The function getMinNorthing returns the minimum northing value of a MGRS
 * zone.
 *
 * Ported from Geotrans' c Lattitude_Band_Value structure table.
 *
 * @private
 * @param {string} zoneLetter The MGRS zone to get the min northing for.
 * @return {number}
 */
function getMinNorthing(zoneLetter) {
  let northing;
  switch (zoneLetter) {
  case 'C':
    northing = 1100000;
    break;
  case 'D':
    northing = 2000000;
    break;
  case 'E':
    northing = 2800000;
    break;
  case 'F':
    northing = 3700000;
    break;
  case 'G':
    northing = 4600000;
    break;
  case 'H':
    northing = 5500000;
    break;
  case 'J':
    northing = 6400000;
    break;
  case 'K':
    northing = 7300000;
    break;
  case 'L':
    northing = 8200000;
    break;
  case 'M':
    northing = 9100000;
    break;
  case 'N':
    northing = 0;
    break;
  case 'P':
    northing = 800000;
    break;
  case 'Q':
    northing = 1700000;
    break;
  case 'R':
    northing = 2600000;
    break;
  case 'S':
    northing = 3500000;
    break;
  case 'T':
    northing = 4400000;
    break;
  case 'U':
    northing = 5300000;
    break;
  case 'V':
    northing = 6200000;
    break;
  case 'W':
    northing = 7000000;
    break;
  case 'X':
    northing = 7900000;
    break;
  default:
    northing = -1;
  }
  if (northing >= 0) {
    return northing;
  }
  else {
    throw new TypeError(`Invalid zone letter: ${zoneLetter}`);
  }

}

return {forward, toPoint, LLtoUTM, UTMtoLL};
})();

export const toUtm = (lat,lon) => mgrsEngine.LLtoUTM({lat,lon});
export const fromUtm = (easting,northing,zoneNumber,zoneLetter) => mgrsEngine.UTMtoLL({easting,northing,zoneNumber,zoneLetter});

export function parseMgrs(value) {
  const reference = value.trim().toUpperCase().replace(/^MGRS\s+/, '').replace(/\s/g, '');
  const match = /^(0?[1-9]|[1-5]\d|60)([C-HJ-NP-X])[A-HJ-NP-Z][A-HJ-NP-V]((?:\d{2}){1,5})$/.exec(reference);
  const message = 'Enter a full WGS84 MGRS grid reference with 2, 4, 6, 8 or 10 digits.';
  if (!match) throw new Error(message);
  const [, zone, band, digits] = match;
  let lon, lat;
  try {
    [lon, lat] = mgrsEngine.toPoint(reference.replace(/^0/, ''));
  } catch {
    throw new Error(message);
  }
  const south = 'CDEFGHJKLMNPQRSTUVWX'.indexOf(band) * 8 - 80;
  const tolerance = 10 ** (5 - digits.length / 2) / 100000;
  if (!Number.isFinite(lon) || Math.abs(lon) > 180 || !Number.isFinite(lat) ||
      lat < south - tolerance || lat > south + (band === 'X' ? 12 : 8) + tolerance ||
      (band === 'X' && ['32', '34', '36'].includes(zone))) {
    throw new Error(message);
  }
  return {lat, lon};
}

export function parseWaypointCsv(text) {
  text = text.replace(/^\uFEFF/, '');
  const field = /(?:"((?:[^"]|"")*)"|([^",\r\n]*))(,|\r\n|\n|\r|$)/y;
  const rows = [];
  let row = [];
  while (field.lastIndex < text.length) {
    const match = field.exec(text);
    if (!match) throw new Error('Invalid CSV quoting.');
    const [, quoted, plain, separator] = match;
    row.push(quoted === undefined ? plain : quoted.replace(/""/g, '"'));
    if (separator === ',' && field.lastIndex < text.length) continue;
    if (separator === ',') row.push('');
    if (row.some(value => value.trim())) rows.push(row);
    row = [];
  }
  const header = rows.shift()?.map(value => value.trim().toLowerCase()) ?? [];
  const columns = Object.fromEntries(['group', 'name', 'latitude', 'longitude', 'mgrs']
    .map(key => [key, header.indexOf(key)]));
  const hasLatLon = columns.latitude >= 0 && columns.longitude >= 0;
  if (columns.group < 0 || columns.name < 0 || (!hasLatLon && columns.mgrs < 0)) {
    throw new Error('CSV needs group and name columns plus latitude and longitude, or mgrs.');
  }
  return rows.map((values, index) => {
    const read = key => values[columns[key]]?.trim() ?? '';
    const unescapeName = value => value.replace(/^'(?=['=+\-@])/, '');
    const group = unescapeName(read('group')), name = unescapeName(read('name'));
    const latitude = read('latitude'), longitude = read('longitude'), mgrs = read('mgrs');
    const fail = message => { throw new Error(`CSV data row ${index + 1}: ${message}`); };
    if (values.length !== header.length || !group || group.length > 60 || name.length > 60) {
      fail('Check the column count and names (up to 60 characters).');
    }
    if (!name && !latitude && !longitude && !mgrs) return {group};
    if (!name) fail('Enter a waypoint name.');
    if (mgrs && !latitude && !longitude) {
      try { return {group, point: {name, ...parseMgrs(mgrs)}}; }
      catch (error) { fail(error.message); }
    }
    const lat = Number(latitude), lon = Number(longitude);
    const decimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;
    if (!decimal.test(latitude) || !decimal.test(longitude) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      fail('Enter valid latitude and longitude in decimal degrees.');
    }
    return {group, point: {name, lat, lon}};
  });
}

export function waypointCsv(groups) {
  const nameField = value => /^['=+\-@]/.test(value) ? "'" + value : value;
  const rows = [['group', 'name', 'latitude', 'longitude']];
  for (const group of groups) {
    const groupName = nameField(group.name);
    if (!group.points.length) rows.push([groupName, '', '', '']);
    for (const point of group.points) rows.push([groupName, nameField(point.name), point.lat, point.lon]);
  }
  return rows.map(row => row.map(value => '"' + String(value).replace(/"/g, '""') + '"').join(',')).join('\r\n') + '\r\n';
}
