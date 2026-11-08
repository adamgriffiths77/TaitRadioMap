import test from 'node:test';
import assert from 'node:assert/strict';
import {pollRows, companionAddress, setupRadioUI, isPaired, forgetPairing} from '../dist/radio-ui.mjs';
import {readFileSync} from 'node:fs';
test('poll list validation', () => {
  assert.deepEqual(pollRows('3000030, 60\n3000029 120'), [{id:'3000030',interval:60},{id:'3000029',interval:120}]);
  for (const data of ['', '0,60', '3000030,0', '3000030,NaN', '3000030,60\n4000030,60']) assert.throws(() => pollRows(data));
});
test('companion must be a loopback HTTP address', () => {
  assert.equal(companionAddress('http://127.0.0.1:8765'), 'http://127.0.0.1:8765');
  for (const url of ['https://example.com', 'http://127.0.0.1/api', 'http://user:password@localhost:8765', 'http://localhost:8765/?key=secret']) assert.throws(() => companionAddress(url));
});
test('an existing pairing can be replaced, rejected keys unlock controls, and forget clears storage', async () => {
  const original = new Map();
  function replace(name, value) { original.set(name, Object.getOwnPropertyDescriptor(globalThis, name)); Object.defineProperty(globalThis, name, {value, configurable:true,writable:true}); }
  const elements = new Map();
  for (const match of readFileSync(new URL('../dist/index.html', import.meta.url),'utf8').matchAll(/id="([^"]+)"/g)) {
    elements.set(match[1], {value:'',textContent:'',hidden:false,disabled:false,type:'password',children:[],
      showModal(){},close(){},replaceChildren(){this.children=[];this.value='';},append(option){this.children.push(option);if(!this.value)this.value=option.value;}});
  }
  const el = id => elements.get(id);
  el('serial-mode').value='listen';el('serial-baud').value='9600';el('serial-flow').value='none';
  el('companion-address').value='http://127.0.0.1:8765';
  const storage = () => { const data=new Map(); return {getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)}; };
  const intervals=[], requests=[];
  let statusFailure=false;
  try {
    replace('document',{getElementById:id=>el(id)});replace('location',{hostname:'private.example'});
    replace('localStorage',storage());replace('sessionStorage',storage());replace('setInterval',fn=>intervals.push(fn));
    replace('Option',class{constructor(text,value){this.text=text;this.value=value;}});
    replace('fetch',async(url,options)=>{
      requests.push([url,options.headers.Authorization]);
      assert.equal(options.method,undefined,'pairing must never start or stop hardware');
      const auth=options.headers.Authorization;
      const denied=auth==='Bearer wrong-key'||statusFailure;
      return {ok:!denied,status:denied?403:200,json:async()=>denied?{error:'Key is invalid'}:url.endsWith('/ports')?{ports:[{device:'COM3',description:'Test port'}]}:{running:auth==='Bearer old-key',settings:{port:'COM3',baud:9600,mode:'listen',flow:'none'},logs:[]}};
    });
    forgetPairing(); await setupRadioUI(()=>{});
    el('companion-key').value='old-key';await el('pair-radio').onclick();
    assert.equal(isPaired(),true);assert.equal(el('start-radio').disabled,true);
    el('companion-key').value='new-key';el('companion-key').oninput();
    assert.equal(isPaired(),false);assert.equal(el('start-radio').disabled,false);assert.equal(el('serial-port').disabled,false);
    await el('pair-radio').onclick();
    assert.equal(isPaired(),true);assert.equal(el('start-radio').disabled,false);
    assert.equal(JSON.parse(sessionStorage.getItem('tait-companion')).key,'new-key');
    assert.equal(requests.at(-1)[1],'Bearer new-key');
    el('companion-key').value='wrong-key';el('companion-key').oninput();await el('pair-radio').onclick();
    assert.equal(isPaired(),false);assert.equal(el('start-radio').disabled,false);assert.equal(el('radio-error').hidden,false);
    el('companion-key').value='new-key';el('companion-key').oninput();await el('pair-radio').onclick();
    statusFailure=true;await intervals[0]();
    assert.equal(isPaired(),false);assert.equal(el('serial-port').disabled,false);
    statusFailure=false;await el('pair-radio').onclick();el('forget-pairing').onclick();
    assert.equal(el('companion-key').value,'');assert.equal(isPaired(),false);assert.equal(sessionStorage.getItem('tait-companion'),null);
  } finally {
    forgetPairing();for(const [name,descriptor]of original){if(descriptor)Object.defineProperty(globalThis,name,descriptor);else delete globalThis[name];}
  }
});
