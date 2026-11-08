let base = '', key = '', paired = false, revision = 0;
export function forgetPairing() { base = ''; key = ''; paired = false; revision++; }
export function companionAddress(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || !(['127.0.0.1', 'localhost'].includes(url.hostname) || /^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)/.test(url.hostname)) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('Use a local companion address such as http://127.0.0.1:8765');
  return url.origin;
}
export function pollRows(value) {
  const rows = value.split(/\r?\n/).map(s => s.trim()).filter(Boolean).map(line => {
    const values = line.split(/[,\s]+/);
    if (values.length !== 2 || !/^[0-9]{1,8}$/.test(values[0]) || Number(values[0]) === 0 || !Number.isFinite(Number(values[1])) || Number(values[1]) < 1) throw new Error('Enter each radio as ID, interval (at least 1 second)');
    return {id:values[0], interval:Number(values[1])};
  });
  if (!rows.length || rows.length > 100) throw new Error('Enter between 1 and 100 radios');
  const suffixes = rows.map(row => row.id.padStart(8, '0').slice(-4));
  if (new Set(suffixes).size !== suffixes.length) throw new Error('Polling IDs need unique last four digits');
  return rows;
}
export const companionUrl = path => new URL(path, base || location.origin).href;
export const isPaired = () => paired;
export async function api(path, options = {}) {
  if (!paired) throw new Error('Open Radio connection to pair with the local companion');
  const requestRevision = revision;
  const response = await fetch(base + path, {...options, headers:{Authorization:`Bearer ${key}`, ...(options.body ? {'Content-Type':'application/json'} : {}), ...options.headers}, cache:'no-store', signal:options.signal || AbortSignal.timeout(12000)});
  const data = await response.json();
  if (requestRevision !== revision) throw new Error('Pairing changed; use the current companion settings');
  if (!response.ok) { const error = new Error(data.error || `Companion returned HTTP ${response.status}`); error.status = response.status; throw error; }
  return data;
}
export async function setupRadioUI(onPaired) {
  const $ = id => document.getElementById(id);
  const local = ['127.0.0.1', 'localhost'].includes(location.hostname);
  let state = null, pending = false;
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('tait-radio-settings') || '{}'); } catch {}
  for (const [id, property] of [['serial-baud','baud'],['serial-mode','mode'],['serial-flow','flow']]) if (saved[property]) $(id).value = saved[property];
  $('poll-radios').value = saved.radios?.map(r => `${r.id}, ${r.interval}`).join('\n') || '3000030, 60\n3000029, 120';
  if (!local && location.protocol === 'http:') $('companion-address').value = location.origin;
  $('companion-pairing').hidden = local;
  $('local-pairing').hidden = !local;
  function error(message = '') { $('radio-error').textContent = message; $('radio-error').hidden = !message; }
  function invalidate(clearInputs = false) {
    forgetPairing(); state = null;
    try { sessionStorage.removeItem('tait-companion'); } catch {}
    if (clearInputs) { $('companion-key').value = ''; $('local-companion-key').value = ''; }
    update();
  }
  function update() {
    const running = !!state?.running;
    $('poll-settings').hidden = $('serial-mode').value !== 'poll';
    $('start-radio').textContent = $('serial-mode').value === 'poll' ? 'Start polling' : 'Start listening';
    $('start-radio').disabled = running || pending;
    $('stop-radio').disabled = !running || pending;
    for (const id of ['serial-port','serial-baud','serial-mode','serial-flow','poll-radios']) $(id).disabled = running || pending;
    $('radio-state').textContent = running ? `${state.settings.mode === 'poll' ? 'Polling' : 'Listening'} · ${state.settings.port} · ${state.settings.baud} baud` : paired ? (state?.exit_code ? `Session exited (${state.exit_code}); check diagnostics` : 'Companion ready · radio stopped') : 'Not connected to companion';
    $('radio-output').textContent = state?.output || '';
    $('radio-logs').textContent = state?.logs?.join('\n') || 'No session messages yet.';
  }
  async function refreshStatus() {
    if (!paired || pending) return;
    const current = revision;
    try { const result = await api('/api/radio/status'); if (current === revision) { state = result; update(); } }
    catch (exc) {
      if (current !== revision) return;
      invalidate();
      error(`Companion unavailable: ${exc.message}. Enter the current key and click Pair / re-pair companion.`);
    }
  }
  async function pair() {
    invalidate();
    const current = revision;
    let authenticated = false;
    if (local) {
      const response = await fetch('/api/bootstrap', {cache:'no-store'});
      if (!response.ok) throw new Error('Restart the local companion to enable radio controls');
      const bootstrap = await response.json();
      if (current !== revision) return;
      key = bootstrap.token; base = ''; $('local-companion-key').value = key;
    } else {
      base = companionAddress($('companion-address').value.trim());
      key = $('companion-key').value.trim();
      if (!key) throw new Error('Enter the companion key printed on the radio PC');
    }
    paired = true;
    try {
      state = await api('/api/radio/status');
      authenticated = true; onPaired();
      const data = await api('/api/radio/ports');
      const selected = state?.running ? state.settings.port : $('serial-port').value || saved.port;
      $('serial-port').replaceChildren();
      if (!data.ports.length) $('serial-port').append(new Option('No serial ports found', ''));
      for (const port of data.ports) $('serial-port').append(new Option(`${port.device} — ${port.description}`, port.device));
      if (selected && data.ports.some(p => p.device === selected)) $('serial-port').value = selected;
      if (state.running) {
        $('serial-baud').value = state.settings.baud; $('serial-mode').value = state.settings.mode; $('serial-flow').value = state.settings.flow;
        if (state.settings.mode === 'poll') $('poll-radios').value = state.settings.radios.map(r => `${r.id}, ${r.interval}`).join('\n');
      }
      if (!local) { try { sessionStorage.setItem('tait-companion', JSON.stringify({base,key})); } catch {} }
      update();
    } catch (exc) { if (current === revision) { paired = authenticated; state = authenticated ? state : null; update(); throw exc; } }
  }
  $('radio-options').onclick = () => { $('radio-dialog').showModal(); refreshStatus(); };
  $('close-radio').onclick = () => $('radio-dialog').close();
  $('serial-mode').onchange = update;
  $('load-ports').onclick = $('pair-radio').onclick = async () => { error(); try { await pair(); } catch (exc) { error(`Cannot connect: ${exc.message}. Start the local companion and allow local-network access if asked. You can also open http://127.0.0.1:8765 directly.`); } };
  $('forget-pairing').onclick = () => { invalidate(true); error(); };
  for (const id of ['companion-key','companion-address']) $(id).oninput = () => { invalidate(); error(); };
  $('show-remote-key').onclick = () => { const visible = $('companion-key').type === 'text'; $('companion-key').type = visible ? 'password' : 'text'; $('show-remote-key').textContent = visible ? 'Show key' : 'Hide key'; };
  $('show-companion-key').onclick = () => { const visible = $('local-companion-key').type === 'text'; $('local-companion-key').type = visible ? 'password' : 'text'; $('show-companion-key').textContent = visible ? 'Show key' : 'Hide key'; };
  $('radio-form').onsubmit = async event => {
    event.preventDefault(); error();
    try {
      const changed = !local && (key !== $('companion-key').value.trim() || base !== companionAddress($('companion-address').value.trim()));
      if (!paired || changed) await pair();
      if (!paired) throw new Error('Pair with the companion before starting a radio session');
      const settings = {port:$('serial-port').value, baud:Number($('serial-baud').value), mode:$('serial-mode').value, flow:$('serial-flow').value};
      if (!settings.port) throw new Error('Select an available serial port');
      settings.radios = settings.mode === 'poll' ? pollRows($('poll-radios').value) : [];
      pending = true; update();
      state = await api('/api/radio/start', {method:'POST', body:JSON.stringify(settings)});
      try { localStorage.setItem('tait-radio-settings', JSON.stringify(settings)); } catch {}
      onPaired();
    } catch (exc) { error(exc.message); } finally { pending = false; update(); }
  };
  $('stop-radio').onclick = async () => {
    error(); pending = true; update();
    try { state = await api('/api/radio/stop', {method:'POST', body:'{}'}); } catch (exc) { error(exc.message); } finally { pending = false; update(); }
  };
  setInterval(refreshStatus, 2000);
  update();
  if (location.protocol !== 'http:') $('radio-dialog').showModal();
  if (local) { try { await pair(); } catch (exc) { error(exc.message); } }
  else {
    try { const savedPair = JSON.parse(sessionStorage.getItem('tait-companion') || 'null'); if (savedPair) { $('companion-address').value = savedPair.base; $('companion-key').value = savedPair.key; } } catch {}
  }
}
