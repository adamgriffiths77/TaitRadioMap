import {WINDOWS, windowLabel, colorFor, normalize, trailSegments, historyPoints, parseKml, afterClear, mapName, MAP_STYLES, mapStyle, coordinateText, COORDINATE_FORMATS, customRadioName, radioName} from './core.mjs';
import {setupRadioUI, api, isPaired} from './radio-ui.mjs';
import {setupMaps, setupWaypoints} from './maps.mjs';


const $ = id => document.getElementById(id);
let aliases = new Map(), editingRadio = null, radioColors = new Map();
try { radioColors = new Map(Object.entries(JSON.parse(localStorage.getItem('tait-radio-colors') || '{}')).filter(([,value]) => /^#[0-9a-f]{6}$/i.test(value))); } catch {}
try { aliases = new Map(Object.entries(JSON.parse(localStorage.getItem('tait-radio-names') || '{}')).filter(([,value]) => typeof value === 'string')); } catch {}
const displayName = radio => radioName(radio.id, aliases);
function editRadioName(radio) {
  editingRadio = radio.id;
  $('radio-name-id').textContent = `Radio ID: ${radio.id}`;
  $('radio-name-input').value = aliases.get(radio.id) || '';
  $('radio-color-input').value = radioColors.get(radio.id) || colorFor(radio.id);
  $('radio-name-dialog').showModal();
  $('radio-name-input').focus();
}
function saveRadioName(value, saveColor = true) {
  if (editingRadio === null) return;
  const name = customRadioName(value);
  if (name) aliases.set(editingRadio, name); else aliases.delete(editingRadio);
  try { localStorage.setItem('tait-radio-names', JSON.stringify(Object.fromEntries(aliases))); } catch {}
  if (saveColor) {
    const color = $('radio-color-input').value;
    if (color.toLowerCase() === colorFor(editingRadio).toLowerCase()) radioColors.delete(editingRadio); else radioColors.set(editingRadio, color);
    try { localStorage.setItem('tait-radio-colors', JSON.stringify(Object.fromEntries(radioColors))); } catch {}
  }
  $('radio-name-dialog').close(); editingRadio = null;
  render();
}
$('radio-name-form').onsubmit = event => { event.preventDefault(); saveRadioName($('radio-name-input').value); };
$('clear-radio-name').onclick = () => saveRadioName('', false);
$('reset-radio-color').onclick = () => { if (editingRadio !== null) $('radio-color-input').value = colorFor(editingRadio); };
$('cancel-radio-name').onclick = () => $('radio-name-dialog').close();
let coordinateFormat = 'latlon';
try { const saved = localStorage.getItem('tait-coordinate-format'); if (COORDINATE_FORMATS.includes(saved)) coordinateFormat = saved; } catch {}
$('coordinate-format').value = coordinateFormat;
$('coordinate-format').onchange = event => {
  coordinateFormat = event.target.value;
  refreshWaypoints();
  try { localStorage.setItem('tait-coordinate-format', coordinateFormat); } catch {}
  render();
};
const local = location.protocol === 'http:';
let radios = [], anchor = 0, layers = new Map(), mode = local ? 'live' : 'files';
let imported = [], busy = false, fitted = false, lastSync = null, dataSignature = '';
let lastPoints = [], clearedThrough = null;
try { const saved = localStorage.getItem('tait-cleared-through'); if (saved !== null && Number.isFinite(Number(saved))) clearedThrough = Number(saved); } catch {}
let hidden;
try { hidden = new Set(JSON.parse(localStorage.getItem('tait-hidden') || '[]')); } catch { hidden = new Set(); }
let historyIndex = 8;
try { const value = Number(localStorage.getItem('tait-history') ?? 8); if (Number.isInteger(value) && value >= 0 && value <= 11) historyIndex = value; } catch {}
$('history-range').value = historyIndex;
const dateFormat = new Intl.DateTimeFormat(undefined, {month:'short', day:'numeric', year:'numeric', hour:'2-digit', minute:'2-digit', second:'2-digit', timeZoneName:'short'});
const timeFormat = new Intl.DateTimeFormat(undefined, {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', second:'2-digit'});
function formatted(time) { return dateFormat.format(new Date(time)); }
function age(time) {
  const seconds = Math.max(0, Math.floor((Date.now() - time) / 1000));
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}
function text(tag, value, className) { const node = document.createElement(tag); node.textContent = value; if (className) node.className = className; return node; }
function notice(message = '') { $('notice').textContent = message; $('notice').hidden = !message; }
function connection(value, error = false) { $('connection').lastElementChild.textContent = value; $('connection').classList.toggle('error', error); }
function savePrefs() { try { localStorage.setItem('tait-hidden', JSON.stringify([...hidden])); localStorage.setItem('tait-history', historyIndex); } catch {} }

const map = window.L ? L.map('map', {zoomControl:false}).setView([-37.85, 145.1], 10) : null;
const refreshWaypoints = setupWaypoints(map, (lat, lon) => coordinateText(lat, lon, coordinateFormat));
let tiles;
function setMapStyle(value) {
  const selected = mapStyle(value), style = MAP_STYLES[selected];
  $('map-style').value = selected;
  try { localStorage.setItem('tait-map-style', selected); } catch {}
  if (!map) return;
  if (tiles) tiles.remove();
  const container = $('map');
  container.classList.toggle('map-greyscale', style.filter === 'greyscale');
  container.classList.toggle('map-dark', style.filter === 'dark');
  const provider = ['dark','greyscale'].includes(selected) ? 'standard' : selected;
  const tileUrl = local ? `/tiles/${provider}/{z}/{x}/{y}.png` : style.url;
  tiles = L.tileLayer(tileUrl, {maxZoom:19,maxNativeZoom:style.maxNativeZoom || 19,
    attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' + (style.extra || '')});
  let pdfOnly = false; try { pdfOnly = localStorage.getItem('tait-pdf-only') === 'true'; } catch {}
  if (!pdfOnly) tiles.addTo(map);
  const current = tiles;
  let failures = 0;
  tiles.on('tileerror', () => {
    if (current === tiles && ++failures === 4) notice(`${style.label} tiles could not load. Try another map style or check your internet connection. Radio data is unaffected.`);
  });
}
for (const [value, style] of Object.entries(MAP_STYLES)) $('map-style').append(new Option(style.label, value));
$('map-style').onchange = event => setMapStyle(event.target.value);
let savedStyle = 'standard';
try { savedStyle = localStorage.getItem('tait-map-style') || 'standard'; } catch {}
setMapStyle(savedStyle);
if (map) {
  L.control.zoom({position:'topright'}).addTo(map);
} else $('map-unavailable').hidden = false;

function popup(radio, point = radio.latest) {
  const node = document.createElement('div');
  node.append(text('div', displayName(radio), 'popup-title'));
  node.append(text('div', `Radio ID: ${radio.id}`, 'popup-time'));
  node.append(text('div', `${point === radio.latest ? 'Last heard' : 'Report time'}: ${formatted(point.time)}`, 'popup-time'));
  node.append(text('div', coordinateText(point.lat, point.lon, coordinateFormat), 'popup-time'));
  node.append(text('p', point.description || 'No additional report details', 'file-note'));
  return node;
}
function focusRadio(radio) {
  if (!map) return;
  if (hidden.has(radio.id)) { hidden.delete(radio.id); savePrefs(); render(); }
  map.setView([radio.latest.lat, radio.latest.lon], Math.max(16, map.getZoom()));
  const marker = layers.get(radio.id)?.marker;
  marker?.bringToFront(); marker?.openPopup();
}
function renderLegend() {
  const list = $('radio-list'); list.replaceChildren();
  const query = $('search').value.trim().toLowerCase();
  for (const radio of radios.filter(r => `${r.id} ${displayName(r)}`.toLowerCase().includes(query))) {
    const row = text('div', '', 'radio-row' + (hidden.has(radio.id) ? ' off' : ''));
    row.style.setProperty('--radio-color', radio.color);
    const check = document.createElement('input'); check.type = 'checkbox'; check.className = 'radio-check';
    check.checked = !hidden.has(radio.id); check.setAttribute('aria-label', `Show radio ${radio.id}`);
    check.onchange = () => { check.checked ? hidden.delete(radio.id) : hidden.add(radio.id); savePrefs(); render(); };
    const content = text('div', '', 'radio-content'), name = text('div', '', 'radio-name');
    const label = text('button', displayName(radio)); label.title = `Centre map on radio ${radio.id}`; label.onclick = () => focusRadio(radio);
    name.append(label, text('span', age(radio.latest.time), 'age'));
    const heard = text('div', `Last heard ${timeFormat.format(new Date(radio.latest.time))}`, 'heard'); heard.title = formatted(radio.latest.time);
    content.append(name, heard, text('div', coordinateText(radio.latest.lat, radio.latest.lon, coordinateFormat), 'coordinates'));
    if (aliases.has(radio.id)) content.insertBefore(text('div', `ID ${radio.id}`, 'radio-id-detail'), heard);
    const edit = text('button', '✎', 'edit-radio-name'); edit.type = 'button';
    edit.title = `Set name or colour for radio ${radio.id}`; edit.setAttribute('aria-label', `Edit name and colour for radio ${radio.id}`);
    edit.onclick = () => editRadioName(radio);
    content.append(edit);
    if (/^[0-9]{1,8}$/.test(radio.id)) {
      const poll = text('button', 'Poll', 'poll-radio');
      poll.type = 'button';
      poll.title = 'Request a fresh location in Poll radios mode';
      poll.setAttribute('aria-label', `Poll radio ${radio.id}`);
      poll.disabled = pendingPolls.has(radio.id);
      poll.onclick = () => pollRadio(radio.id, poll);
      content.append(poll);
    }
    row.append(check, content); list.append(row);
  }
  if (radios.length && !list.children.length) list.append(text('div', 'No matching radio IDs or names', 'no-search'));
  $('radio-count').textContent = radios.length;
  $('empty').hidden = radios.length > 0;
  list.hidden = radios.length === 0;
  $('toggle-all').textContent = radios.some(r => !hidden.has(r.id)) ? 'Hide all' : 'Show all';
}

const pendingPolls = new Set();
async function pollRadio(id, button) {
  const status = $('radio-poll-status');
  pendingPolls.add(id);
  button.disabled = true;
  status.hidden = false;
  status.textContent = `Requesting a location from ${id}…`;
  try {
    const result = await api('/api/radio/poll', {method:'POST', body:JSON.stringify({id})});
    status.textContent = `Poll requested for ${result.id}. The position updates when a report arrives.`;
  } catch (error) {
    status.textContent = error.message;
  } finally {
    pendingPolls.delete(id);
    if (button.isConnected) button.disabled = false;
    else renderLegend();
  }
}
function renderMap() {
  for (const item of layers.values()) item.group.remove();
  layers.clear();
  const minutes = WINDOWS[historyIndex];
  let count = 0;
  radios.forEach((radio, index) => {
    if (hidden.has(radio.id)) return;
    const segments = trailSegments(radio, minutes, anchor);
    const reports = historyPoints(radio, minutes, anchor);
    count += reports.length;
    if (!map) return;
    const group = L.layerGroup().addTo(map);
    for (const points of segments) {
      L.polyline(points.map(p => [p.lat, p.lon]), {color:radio.color, weight:3, opacity:.65, smoothFactor:1}).addTo(group);
    }
    for (const report of reports) {
      if (report === radio.latest) continue;
      const dot = L.circleMarker([report.lat, report.lon], {radius:3.5, color:'#fff', weight:1, fillColor:radio.color, fillOpacity:.9, className:'report-dot'}).addTo(group);
      dot.bindPopup(popup(radio, report));
      dot.bindTooltip(text('span', `${displayName(radio)} · ID ${radio.id} · ${formatted(report.time)}`), {direction:'top'});
    }
    const latest = radio.latest;
    L.circleMarker([latest.lat, latest.lon], {radius:15, stroke:false, fillColor:radio.color, fillOpacity:.13, interactive:false}).addTo(group);
    const marker = L.circleMarker([latest.lat, latest.lon], {radius:7, color:'#fff', weight:2.5, fillColor:radio.color, fillOpacity:1}).addTo(group);
    marker.bindPopup(popup(radio));
    const tooltip = text('span', displayName(radio)); tooltip.title = `Radio ID: ${radio.id}`;
    marker.bindTooltip(tooltip, {permanent:true, direction:index % 2 ? 'left' : 'right', offset:[index % 2 ? -12 : 12, 0], className:'radio-label'});
    layers.set(radio.id, {group, marker});
  });
  const visible = radios.filter(r => !hidden.has(r.id)).length;
  $('visible-summary').textContent = radios.length ? `${visible} of ${radios.length} radios visible` : 'No radios loaded';
  $('point-count').textContent = `${count.toLocaleString()} track points`;
  $('history-label').textContent = windowLabel(minutes);
  $('history-range').setAttribute('aria-valuetext', windowLabel(minutes));
  $('history-anchor').textContent = anchor ? `History ending ${timeFormat.format(new Date(anchor))}` : 'No recorded positions yet';
  $('history-anchor').title = anchor ? `History is measured backwards from the newest report: ${formatted(anchor)}` : '';
}
function render() {
  for (const radio of radios) radio.color = radioColors.get(radio.id) || colorFor(radio.id);
  renderLegend(); renderMap();
}
function fit() {
  if (!map) return;
  const points = radios.filter(r => !hidden.has(r.id)).flatMap(r => {
    const trails = trailSegments(r, WINDOWS[historyIndex], anchor).flat();
    return [...trails, r.latest].map(p => [p.lat, p.lon]);
  });
  if (points.length) map.fitBounds(points, {paddingTopLeft:[45,70], paddingBottomRight:[65,210], maxZoom:17});
}
function setData(points) {
  lastPoints = points;
  const signature = JSON.stringify(points);
  if (signature === dataSignature) return;
  dataSignature = signature;
  radios = normalize(afterClear(points, clearedThrough));
  anchor = radios.length ? Math.max(...radios.map(r => r.latest.time)) : 0;
  render();
  $('clear-history').disabled = !radios.length;
  $('restore-history').disabled = clearedThrough === null;
  $('empty').querySelector('h2').textContent = clearedThrough === null ? 'Ready for your radios' : 'Waiting for new reports';
  $('empty').querySelector('p').textContent = clearedThrough === null ? 'Open a KML file to see positions and tracks, or start the local viewer for automatic updates.' : 'History and the radio list have been cleared. Newer reports will appear here. Use Panels → Restore saved data to bring back previous reports.';
  if (!fitted && radios.length) { fit(); fitted = true; }
}
async function loadLive() {
  if (busy || mode !== 'live') return;
  busy = true;
  try {
    let payload;
    if (local && !isPaired()) {
      const response = await fetch('/api/viewer/positions', {cache:'no-store',signal:AbortSignal.timeout(12000)});
      if (!response.ok) throw new Error(`Shared viewer returned HTTP ${response.status}`);
      payload = await response.json();
    } else payload = await api('/api/positions');
    if (mode !== 'live') return;
    if (!Array.isArray(payload.points)) throw new Error('Position source returned invalid data');
    if (!payload.errors?.length || payload.points.length) setData(payload.points);
    lastSync = Date.now();
    connection(payload.errors?.length ? 'Source needs attention' : 'Local · updating', !!payload.errors?.length);
    $('source-title').textContent = payload.sources?.map(s => s.name).join(' + ') || 'Local KML files';
    $('source-detail').textContent = `Refresh every 5s · checked ${new Date(lastSync).toLocaleTimeString()}`;
    notice(payload.errors?.join(' · ') || '');
  } catch (error) {
    connection('Connection interrupted', true);
    notice(`Cannot refresh local KML data. ${error.message}. Existing positions are retained.`);
  } finally { busy = false; }
}
async function loadFiles(files) {
  if (!files.length) return;
  try {
    const points = [];
    for (const file of files) {
      if (file.size > 50 * 1024 * 1024) throw new Error(`${file.name}: file exceeds 50 MB`);
      points.push(...parseKml(await file.text(), file.name));
    }
    if (!normalize(points).length) throw new Error('No timestamped point locations found in these KML files');
    mode = 'files'; imported = [...files]; fitted = false; setData(points);
    connection('KML snapshot');
    $('source-title').textContent = files.map(f => f.name).join(' + ');
    $('source-detail').textContent = local ? 'File snapshot · ↻ returns to local updates' : 'Open again to load newer data';
    notice('');
  } catch (error) { notice(`${error.message}. The previous dataset is retained.`); }
}
$('open-files').onclick = $('empty-open').onclick = () => $('files').click();
$('files').onchange = async event => { await loadFiles([...event.target.files]); event.target.value = ''; };
$('search').oninput = renderLegend;
$('toggle-all').onclick = () => {
  const hide = radios.some(r => !hidden.has(r.id));
  radios.forEach(r => hide ? hidden.add(r.id) : hidden.delete(r.id));
  savePrefs(); render();
};
$('history-range').oninput = event => { historyIndex = Number(event.target.value); savePrefs(); renderMap(); };
$('fit').onclick = fit;
$('clear-history').onclick = () => {
  if (!radios.length) return;
  clearedThrough = anchor;
  try { localStorage.setItem('tait-cleared-through', String(clearedThrough)); } catch {}
  dataSignature = ''; fitted = false; setData(lastPoints);
};
$('restore-history').onclick = () => {
  clearedThrough = null;
  try { localStorage.removeItem('tait-cleared-through'); } catch {}
  dataSignature = ''; fitted = false; setData(lastPoints);
};
$('refresh').onclick = () => { if (local || isPaired()) { mode = 'live'; loadLive(); } else if (imported.length) loadFiles(imported); else $('files').click(); };
setInterval(() => { if (mode === 'live') loadLive(); }, 5000);
setInterval(renderLegend, 30000);
new ResizeObserver(() => map?.invalidateSize()).observe($('map'));
setupPanels();
render();
$('clear-history').disabled = true;
$('restore-history').disabled = clearedThrough === null;
mode = local ? 'live' : 'files';
setupRadioUI(() => { mode = 'live'; fitted = false; loadLive(); });
connection(local ? 'Connecting to shared data' : 'Radio not connected'); $('source-detail').textContent = local ? 'Shared radio feed · refresh every 5s' : 'Connect a radio or open KML files';
if (local) loadLive();

function setupPanels() {
  const $ = id => document.getElementById(id);
  $('maps-controls').prepend($('map-name-form'), $('map-style').parentElement, $('coordinate-format').parentElement);
  $('maps-controls').append($('cache-controls'));
  setupMaps(map, {getTiles:() => tiles});
  function applyName(value) {
    const name = mapName(value);
    $('map-name').textContent = name;
    $('map-name-input').value = name;
    document.title = `${name} · Radio Map`;
    document.querySelector('.brand').setAttribute('aria-label', `${name} Radio Map home`);
    try { localStorage.setItem('tait-map-name', name); } catch {}
  }
  let savedName = 'TAIT';
  try { savedName = localStorage.getItem('tait-map-name') || 'TAIT'; } catch {}
  applyName(savedName);
  $('map-name-form').onsubmit = event => { event.preventDefault(); applyName($('map-name-input').value); };
  let state = {legend:true, history:true, status:true, large:false};
  try { state = {...state, ...JSON.parse(localStorage.getItem('tait-panels') || '{}')}; } catch {}
  const history = document.querySelector('.history');
  function save() { try { localStorage.setItem('tait-panels', JSON.stringify(state)); } catch {} }
  function apply() {
    document.querySelector('.sidebar').hidden = !state.legend;
    document.querySelector('.workspace').classList.toggle('no-legend', !state.legend);
    history.hidden = !state.history;
    document.querySelector('.map-caption').hidden = !state.status;
    document.querySelector('.map-panel').classList.toggle('no-map-status', !state.status);
    history.classList.toggle('large', state.large);
    $('size-history').textContent = state.large ? 'Compact' : 'Larger';
    for (const part of ['legend','history','status']) $('show-' + part).checked = !!state[part];
    if (state.width && state.height) { history.style.width = state.width + 'px'; history.style.height = state.height + 'px'; }
    else { history.style.width = ''; history.style.height = ''; }
    save();
  }
  for (const part of ['legend','history','status']) $('show-' + part).onchange = event => { state[part] = event.target.checked; apply(); };
  $('hide-legend').onclick = () => { state.legend = false; apply(); };
  $('hide-history').onclick = () => { state.history = false; apply(); };
  $('size-history').onclick = () => { state.large = !state.large; delete state.width; delete state.height; apply(); };
  $('reset-panels').onclick = () => { state = {legend:true,history:true,status:true,large:false}; apply(); };
  new ResizeObserver(() => {
    // Native CSS resize writes inline pixel sizes. Ignore ordinary viewport
    // changes and visibility changes so they do not overwrite the user's size.
    if (!history.hidden && history.style.width && history.style.height) {
      state.width = parseFloat(history.style.width); state.height = parseFloat(history.style.height); save();
    }
  }).observe(history);
  apply();
}

async function cacheStatus(data) {
 try {
  if (!isPaired()) return;
  const status = await api('/api/cache', data ? {method:'POST',body:JSON.stringify(data)} : {});
  $('cache-status').textContent = `${(status.bytes / 1048576).toFixed(1)} MB · ${status.tiles} tiles · limit ${status.limit_mb} MB`;
  if (document.activeElement !== $('cache-limit')) $('cache-limit').value = status.limit_mb;
 } catch (error) { $('cache-status').textContent = error.message; }
}
$('cache-save').onclick = () => cacheStatus({limit_mb:Number($('cache-limit').value)});
$('cache-clear').onclick = () => cacheStatus({clear:true});
setInterval(() => cacheStatus(), 10000); cacheStatus();
