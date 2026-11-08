import {toUtm, fromUtm} from './core.mjs';
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
