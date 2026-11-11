import {toUtm, fromUtm, parseMgrs, parseWaypointCsv, waypointCsv} from './core.mjs';
import {api, isPaired, companionUrl} from './radio-ui.mjs';

const $ = id => document.getElementById(id);
const remember = (key,value) => { try { localStorage.setItem(key,value); } catch {} };
const saved = (key,fallback='') => { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } };
export function setupMaps(map, {getTiles}) {
  let grid=null, overlay=null, catalog=[], loading=false, importing=false;
  let selected=saved('tait-pdf-map'), gridMode=saved('tait-grid','off');
  if (!['off','latlon','utm'].includes(gridMode)) gridMode='off';
  $('map-grid').value=gridMode;
  $('pdf-only').checked=saved('tait-pdf-only')==='true';
  $('pdf-opacity').value=saved('tait-pdf-opacity','100');
  const status=message => { $('pdf-status').textContent=message; };
  const local=location.protocol==='http:';
  $('pdf-fit').disabled=$('pdf-remove').disabled=true;
  const line=(points,label,position) => {
    L.polyline(points,{color:'#3d5763',weight:1,opacity:.55,interactive:false}).addTo(grid);
    if (position && map.getBounds().contains(position)) {
      const node=document.createElement('span');node.textContent=label;
      L.marker(position,{interactive:false,keyboard:false,icon:L.divIcon({className:'grid-label',html:node,iconSize:null})}).addTo(grid);
    }
  };
  function drawGrid() {
    if (!map) return;
    grid?.remove(); grid=L.layerGroup().addTo(map);
    const info=$('grid-description'); info.textContent='';
    if(gridMode==='off') return;
    const bounds=map.getBounds(), center=map.getCenter();
    if (gridMode==='latlon') {
      const span=Math.max(bounds.getNorth()-bounds.getSouth(),bounds.getEast()-bounds.getWest());
      const choices=[.001,.002,.005,.01,.02,.05,.1,.2,.5,1,2,5,10,20,30,60];
      const step=choices.find(value=>span/value<=18)||60;
      const south=Math.max(-85,bounds.getSouth()),north=Math.min(85,bounds.getNorth());
      const west=Math.max(-180,bounds.getWest()),east=Math.min(180,bounds.getEast());
      const format=value=>`${Math.abs(value).toFixed(step<1?3:1)}°`;
      for(let lat=Math.ceil(south/step)*step;lat<=north;lat+=step) line([[lat,west],[lat,east]],format(lat)+(lat<0?'S':'N'),[lat,west+(east-west)*.05]);
      for(let lon=Math.ceil(west/step)*step;lon<=east;lon+=step) line([[south,lon],[north,lon]],format(lon)+(lon<0?'W':'E'),[south+(north-south)*.08,lon]);
      info.textContent=`WGS84 latitude/longitude · spacing ${step}°`;
      return;
    }
    if(center.lat < -80 || center.lat >84 || map.getZoom()<8 || center.lng < -180 || center.lng>180) {
      info.textContent='Zoom in (level 8+) within UTM latitudes 80°S–84°N to show the metric grid.';return;
    }
    const utm=toUtm(center.lat,center.lng);
    const radius=Math.min(500000,map.distance(bounds.getSouthWest(),bounds.getNorthEast())*.65);
    const step=[100,1000,10000,100000].find(value=>radius*2/value<=24)||100000;
    const e0=Math.max(100000,utm.easting-radius),e1=Math.min(900000,utm.easting+radius);
    const n0=Math.max(0,utm.northing-radius),n1=Math.min(10000000,utm.northing+radius);
    const convert=(e,n)=>{const p=fromUtm(e,n,utm.zoneNumber,utm.zoneLetter);return [p.lat,p.lon];};
    for(let e=Math.ceil(e0/step)*step;e<=e1;e+=step) {
      const points=Array.from({length:33},(_,i)=>convert(e,n0+(n1-n0)*i/32));
      line(points,`${e} E`,convert(e,utm.northing));
    }
    for(let n=Math.ceil(n0/step)*step;n<=n1;n+=step) {
      const points=Array.from({length:33},(_,i)=>convert(e0+(e1-e0)*i/32,n));
      line(points,`${n} N`,convert(utm.easting,n));
    }
    info.textContent=`WGS84 UTM zone ${utm.zoneNumber}${utm.zoneLetter} · ${step>=1000?step/1000+' km':step+' m'} spacing. Full easting/northing labels. Grid uses the centre zone; check paper-map zone and datum.`;
  }
  $('map-grid').onchange=()=>{gridMode=$('map-grid').value;remember('tait-grid',gridMode);drawGrid();};
  map?.on('moveend',drawGrid);drawGrid();
  function tileVisibility() {
    if (!map) return;
    const tiles=getTiles();if(!tiles)return;
    if($('pdf-only').checked) tiles.remove(); else if(!map.hasLayer(tiles)) tiles.addTo(map);
  }
  $('map-style').addEventListener('change',tileVisibility);
  $('pdf-only').onchange=()=>{remember('tait-pdf-only',$('pdf-only').checked);tileVisibility();};
  function showPdf() {
    overlay?.remove();overlay=null;
    const item=catalog.find(item=>item.id===selected);
    $('pdf-fit').disabled=$('pdf-remove').disabled=!item;
    if(item && map) {
      overlay=L.imageOverlay(companionUrl(`/maps/${item.id}.png`),item.bounds,{opacity:Number($('pdf-opacity').value)/100,interactive:false,attribution:'PDF map: '+escapeAttribution(item.name)}).addTo(map);
      overlay.on('error',()=>status('PDF image could not load. Check the companion connection.'));
      status(`${item.name} · page ${item.page}, frame ${item.viewport} · ${item.crs} · ${(item.bytes/1048576).toFixed(1)} MB. Check alignment against known locations.`);
    }
    tileVisibility();
  }
  $('pdf-map').onchange=()=>{selected=$('pdf-map').value;remember('tait-pdf-map',selected);showPdf();};
  $('pdf-opacity').oninput=()=>{remember('tait-pdf-opacity',$('pdf-opacity').value);overlay?.setOpacity(Number($('pdf-opacity').value)/100);};
  $('pdf-fit').onclick=()=>{const item=catalog.find(item=>item.id===selected);if(item&&map)map.fitBounds(item.bounds);};
  async function refresh() {
    if(loading||importing)return;
    if(!local&&!isPaired()){status('Pair with the radio PC to view its PDF maps, or open its local/network viewer.');return;}
    loading=true;
    try {
      let payload;
      if(local){const response=await fetch('/api/viewer/maps',{cache:'no-store'});if(!response.ok)throw new Error('Restart the companion to enable PDF map support');payload=await response.json();}
      else payload=await api('/api/viewer/maps');
      if(JSON.stringify(catalog)!==JSON.stringify(payload.maps)) {
        catalog=payload.maps||[];
        $('pdf-map').replaceChildren(new Option('None',''),...catalog.map(item=>new Option(item.name+` · p${item.page}`,item.id)));
        if(selected&&!catalog.some(item=>item.id===selected))selected='';
        $('pdf-map').value=selected;showPdf();
      }
      if(!catalog.length)status('No PDF maps stored yet. Import a geospatial PDF to get started.');
    }catch(error){status(error.message);}finally{loading=false;}
  }
  $('pdf-import').onclick=()=>{
    if(!isPaired()){status('Open Radio connection and pair with the companion before importing. Viewing existing PDF maps does not require a key on the LAN.');return;}
    $('pdf-file').click();
  };
  $('pdf-file').onchange=async()=>{
    const file=$('pdf-file').files[0];$('pdf-file').value='';if(!file)return;
    if(file.size>50*1024*1024){status('PDF exceeds the 50 MB limit.');return;}
    importing=true;$('pdf-import').disabled=true;status('Importing and projecting PDF map…');
    try{
      const query=new URLSearchParams({name:file.name,page:$('pdf-page').value,viewport:$('pdf-viewport').value});
      const item=await api('/api/maps/import?'+query,{method:'POST',body:file,headers:{'Content-Type':'application/pdf'},signal:AbortSignal.timeout(180000)});
      selected=item.id;remember('tait-pdf-map',selected);catalog=[];
    }catch(error){status(error.message);return;}finally{importing=false;$('pdf-import').disabled=false;}
    await refresh();$('pdf-fit').click();
  };
  $('pdf-remove').onclick=async()=>{
    if(!selected)return;
    try{await api('/api/maps/remove',{method:'POST',body:JSON.stringify({id:selected})});selected='';remember('tait-pdf-map','');await refresh();showPdf();status('PDF map deleted from the radio PC.');}
    catch(error){status(error.message);}
  };
  tileVisibility();refresh();setInterval(refresh,15000);
}
function escapeAttribution(value) {
  const span=document.createElement('span');span.textContent=value;return span.innerHTML;
}

export function setupWaypoints(map, formatCoordinates) {
  const storageKey = 'tait-waypoint-groups';
  const panel = $('waypoints');
  const groupSelect = $('waypoint-group');
  const form = $('waypoint-form');
  const name = $('waypoint-name');
  const latitude = $('waypoint-lat');
  const longitude = $('waypoint-lon');
  const entryFormat = $('waypoint-format');
  const mgrs = $('waypoint-mgrs');
  const csv = $('waypoint-csv');
  const pick = $('waypoint-pick');
  const layer = map ? L.layerGroup().addTo(map) : null;
  let groups = [];
  try {
    groups = JSON.parse(localStorage.getItem(storageKey) ?? '[]');
    if (!Array.isArray(groups)) groups = [];
  } catch {}
  let selected = groups.length ? 0 : -1;
  let editing = -1;
  let picking = false;

  function status(message) {
    $('waypoint-status').textContent = message;
  }

  function setPicking(value) {
    picking = value;
    pick.setAttribute('aria-pressed', String(value));
    pick.textContent = value ? 'Cancel pick' : 'Pick on map';
    map?.getContainer().classList.toggle('picking-waypoint', value);
  }

  function resetForm() {
    const format = entryFormat.value;
    form.reset();
    setFormat(format);
    editing = -1;
    $('waypoint-save').textContent = 'Add waypoint';
    $('waypoint-cancel').hidden = true;
    setPicking(false);
  }

  function setFormat(format) {
    entryFormat.value = format;
    const grid = format === 'mgrs';
    $('waypoint-latlon-fields').hidden = latitude.disabled = longitude.disabled = grid;
    $('waypoint-mgrs-field').hidden = mgrs.disabled = !grid;
  }
  entryFormat.onchange = () => setFormat(entryFormat.value);

  function button(label, action) {
    const node = document.createElement('button');
    node.type = 'button';
    node.textContent = label;
    node.onclick = action;
    return node;
  }

  function draw() {
    layer?.clearLayers();
    for (const group of groups) {
      if (!layer || !group.visible) continue;
      for (const point of group.points) {
        const popup = document.createElement('div');
        const title = document.createElement('strong');
        title.textContent = point.name;
        popup.append(title, document.createElement('br'),
          group.name, document.createElement('br'), formatCoordinates(point.lat, point.lon));
        const icon = L.divIcon({className: 'waypoint-marker', iconSize: [16, 16]});
        L.marker([point.lat, point.lon], {icon, title: point.name})
          .bindPopup(popup).addTo(layer);
      }
    }
    const list = $('waypoint-list');
    list.replaceChildren();
    const group = groups[selected];
    if (!group) return;
    for (const [index, point] of group.points.entries()) {
      const row = document.createElement('li');
      const title = document.createElement('strong');
      title.textContent = point.name;
      const coordinates = document.createElement('small');
      coordinates.textContent = formatCoordinates(point.lat, point.lon);
      const actions = document.createElement('div');
      actions.className = 'waypoint-actions';
      const locate = button('Locate', () => {
        map.setView([point.lat, point.lon], Math.max(map.getZoom(), 15));
        panel.open = false;
        panel.closest('.layout-menu').open = false;
      });
      locate.disabled = !map;
      actions.append(locate, button('Edit', () => {
        setPicking(false);
        setFormat('latlon');
        editing = index;
        name.value = point.name;
        latitude.value = point.lat;
        longitude.value = point.lon;
        $('waypoint-save').textContent = 'Save changes';
        $('waypoint-cancel').hidden = false;
        name.focus();
      }), button('Delete', () => {
        if (!confirm(`Delete waypoint “${point.name}”?`)) return;
        group.points.splice(index, 1);
        resetForm();
        save('Waypoint deleted.');
      }));
      row.append(title, coordinates, actions);
      list.append(row);
    }
  }

  function render() {
    groupSelect.replaceChildren(...groups.map((group, index) => new Option(group.name, index)));
    groupSelect.value = selected;
    $('waypoint-group-controls').hidden = selected < 0;
    $('waypoint-visible').checked = groups[selected]?.visible ?? false;
    $('waypoint-export').disabled = !groups.length;
    draw();
  }

  function save(message) {
    try {
      localStorage.setItem(storageKey, JSON.stringify(groups));
      status(message);
    } catch {
      status('Browser storage is unavailable. Changes will be lost on reload.');
    }
    render();
  }

  $('waypoint-group-form').onsubmit = event => {
    event.preventDefault();
    const input = $('waypoint-group-name');
    const value = input.value.trim();
    if (!value) return status('Enter a group name.');
    if (groups.some(group => group.name === value)) return status('A group with that name already exists.');
    groups.push({name: value, visible: true, points: []});
    selected = groups.length - 1;
    input.value = '';
    resetForm();
    save('Group added.');
    name.focus();
  };
  groupSelect.onchange = () => {
    selected = Number(groupSelect.value);
    resetForm();
    status('');
    render();
  };
  $('waypoint-visible').onchange = event => {
    groups[selected].visible = event.target.checked;
    save(event.target.checked ? 'Group shown.' : 'Group hidden.');
  };
  $('waypoint-rename').onclick = () => {
    const group = groups[selected];
    const value = prompt('Group name', group.name)?.trim();
    if (!value) return;
    if (value.length > 60) return status('Group names can have up to 60 characters.');
    if (groups.some(other => other !== group && other.name === value)) {
      return status('A group with that name already exists.');
    }
    group.name = value;
    save('Group renamed.');
  };
  $('waypoint-delete-group').onclick = () => {
    if (!confirm(`Delete group “${groups[selected].name}” and all its waypoints?`)) return;
    groups.splice(selected, 1);
    selected = Math.min(selected, groups.length - 1);
    resetForm();
    save('Group deleted.');
  };
  $('waypoint-cancel').onclick = () => { resetForm(); status('Edit cancelled.'); };
  form.onsubmit = event => {
    event.preventDefault();
    const label = name.value.trim();
    if (!label) return status('Enter a waypoint name.');
    let coordinates;
    try {
      coordinates = entryFormat.value === 'mgrs' ? parseMgrs(mgrs.value)
        : {lat: latitude.valueAsNumber, lon: longitude.valueAsNumber};
    } catch (error) {
      status(error.message);
      mgrs.focus();
      return;
    }
    const points = groups[selected].points;
    const message = editing < 0 ? 'Waypoint added.' : 'Waypoint updated.';
    points[editing < 0 ? points.length : editing] = {name: label, ...coordinates};
    resetForm();
    save(message);
  };
  pick.disabled = !map;
  pick.onclick = () => {
    setPicking(!picking);
    status(picking ? 'Click the map to fill in the coordinates.' : 'Map pick cancelled.');
  };
  panel.addEventListener('toggle', () => {
    if (!panel.open && picking) {
      setPicking(false);
      status('');
    }
  });
  panel.closest('.layout-menu').addEventListener('toggle', event => {
    if (!event.currentTarget.open && picking) {
      setPicking(false);
      status('');
    }
  });
  map?.on('click', event => {
    if (!picking) return;
    const point = map.wrapLatLng(event.latlng);
    setFormat('latlon');
    latitude.value = point.lat.toFixed(6);
    longitude.value = point.lng.toFixed(6);
    setPicking(false);
    status('Coordinates selected. Save to place the waypoint.');
    (name.value.trim() ? $('waypoint-save') : name).focus();
  });
  $('waypoint-import').onclick = () => csv.click();
  csv.onchange = async () => {
    const [file] = csv.files;
    csv.value = '';
    if (!file) return;
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error('Choose a CSV file up to 2 MB.');
      const rows = parseWaypointCsv(await file.text());
      const byName = new Map(groups.map(group => [group.name, group]));
      const seen = new Map();
      let added = 0, created = 0;
      for (const {group: label, point} of rows) {
        let group = byName.get(label);
        if (!group) {
          group = {name: label, visible: true, points: []};
          groups.push(group);
          byName.set(label, group);
          created++;
        }
        if (!point) continue;
        if (!seen.has(group)) {
          seen.set(group, new Set(group.points.map(item => JSON.stringify([item.name, item.lat, item.lon]))));
        }
        const keys = seen.get(group);
        const key = JSON.stringify([point.name, point.lat, point.lon]);
        if (keys.has(key)) continue;
        keys.add(key);
        group.points.push(point);
        added++;
      }
      if (selected < 0 && groups.length) selected = 0;
      save(`Imported ${added} waypoint(s) and ${created} new group(s). Exact duplicates were skipped.`);
    } catch (error) {
      status(error.message);
    }
  };
  $('waypoint-export').onclick = () => {
    const url = URL.createObjectURL(new Blob([waypointCsv(groups)], {type: 'text/csv;charset=utf-8'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'waypoints.csv';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  render();
  return draw;
}
