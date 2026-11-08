import test from 'node:test';
import assert from 'node:assert/strict';
import {normalize, trailSegments, historyPoints, windowLabel, colorFor, afterClear, mapName, mapStyle, MAP_STYLES, coordinateText, customRadioName, radioName} from '../dist/core.mjs';
const p = (id, minutes, session = 'one') => ({id, time:new Date(minutes * 60000).toISOString(), lat:-37.9, lon:145.3, session});
test('radio names retain original IDs and clearing returns to the ID',()=>{
  const names = new Map([['0030','  Team   Alpha ']]);
  assert.equal(radioName('0030',names),'Team Alpha');
  assert.equal(radioName('3000029',names),'3000029');
  assert.equal(radioName('3000030',names),'3000030');
  names.delete('0030'); assert.equal(radioName('0030',names),'0030');
  assert.equal(customRadioName('x'.repeat(50)).length,40);
  assert.equal(customRadioName(null),'');
});
test('MGRS matches published conversion vector and formats easting/northing precision',()=>{
  // proj4js/mgrs published test vector: 11SPA7234911844.
  assert.equal(coordinateText(36.2361322,-115.0820944,'mgrs5'),'MGRS 11S PA 72349 11844');
  assert.equal(coordinateText(36.2361322,-115.0820944,'mgrs3'),'MGRS 11S PA 723 118');
  assert.equal(coordinateText(0,0,'mgrs5'),'MGRS 31N AA 66021 00000');
  assert.match(coordinateText(-37.91105,145.32633,'mgrs3'),/^MGRS 55H CU \d{3} \d{3}$/);
  assert.match(coordinateText(-37.91105,145.32633,'mgrs4'),/^MGRS 55H CU \d{4} \d{4}$/);
  assert.match(coordinateText(88,0,'mgrs3'),/unavailable in polar regions/);
  assert.equal(coordinateText(NaN,0,'mgrs3'),'Coordinates unavailable');
  assert.equal(coordinateText(-37.9,145.3,'latlon'),'-37.900000, 145.300000');
});
test('map styles use HTTPS, reject unknown saved settings and retain a standard fallback',()=>{
  assert.equal(mapStyle('dark'),'dark'); assert.equal(mapStyle('untrusted'),'standard');
  assert.equal(mapStyle('__proto__'),'standard');
  for(const style of Object.values(MAP_STYLES)) assert.ok(style.url.startsWith('https://'));
  assert.equal(MAP_STYLES.topographic.maxNativeZoom,17);
});
test('report dots include isolated session points, respect the window, and keep timestamps', () => {
  const [radio] = normalize([p('0030',1),p('0030',5,'other'),p('0030',6,'third')]);
  assert.equal(historyPoints(radio,Infinity,360000).length,3);
  assert.equal(trailSegments(radio,Infinity,360000).length,0);
  assert.deepEqual(historyPoints(radio,1,360000).map(p=>p.time),[300000,360000]);
  assert.deepEqual(historyPoints(radio,0,360000),[]);
});
test('map name is user-defined, trimmed, bounded, and defaults to TAIT', () => {
  assert.equal(mapName('  Search   Team  '), 'Search Team');
  assert.equal(mapName(' '), 'TAIT'); assert.equal(mapName(null), 'TAIT');
  assert.equal(mapName('a'.repeat(50)).length,40);
});
test('clear removes radios and history, refresh does not restore them, and newer reports reappear', () => {
  const old = [p('0030', 1), p('0030', 2), p('3000029', 3)];
  assert.deepEqual(normalize(afterClear(old, 180000)), []);
  const radios = normalize(afterClear([...old, p('0030', 4)], 180000));
  assert.deepEqual(radios.map(r => r.id), ['0030']);
  assert.equal(radios[0].points.length, 1);
  assert.equal(normalize(afterClear(old, null)).length, 2);
  assert.equal(old.length, 3);
});
test('latest positions use timestamps, preserve zero suffixes and deduplicate imports', () => {
  const radios = normalize([p('0030', 5), p('0030', 2), p('0030', 5), p('3000029', 3), {...p('bad', 6), lat:NaN}]);
  assert.equal(radios.length, 2); assert.equal(radios[0].id, '0030');
  assert.equal(radios[0].latest.time, 300000); assert.equal(radios[0].points.length, 2);
});
test('history windows retain latest marker data and do not join sessions', () => {
  const [radio] = normalize([p('0030', 1), p('0030', 2), p('0030', 9, 'two'), p('0030', 10, 'two')]);
  assert.equal(trailSegments(radio, Infinity, 600000).length, 2);
  assert.equal(trailSegments(radio, 5, 600000).length, 1);
  assert.equal(trailSegments(radio, 0, 600000).length, 0);
  assert.equal(radio.latest.time, 600000);
});
test('labels and colors remain stable', () => {
  assert.equal(windowLabel(0), 'Latest positions only'); assert.equal(windowLabel(1440), '1 day');
  assert.equal(windowLabel(Infinity), 'All recorded history'); assert.equal(colorFor('0030'), colorFor('0030'));
});
