import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../tallyboard/static/console.js', import.meta.url), 'utf8');
function browser() {
  let now = 1000, nextId = 0;
  const timers = new Map(), nodes = new Map(), requests = [];
  const node = () => ({ style: {}, textContent: '', innerHTML: '', className: '', scrollHeight: 0, clientHeight: 800,
    getElementsByClassName: () => [], removeChild: () => {}, setAttribute() {}, removeAttribute() {} });
  const document = { body: node(), getElementById(id) { if (!nodes.has(id)) nodes.set(id,node()); return nodes.get(id); }, addEventListener() {}, getElementsByClassName: () => [], querySelectorAll: () => [], documentElement: {} };
  let reloads = 0;
  class XHR {
    constructor() { requests.push(this); }
    open(method,url) { this.method=method;this.url=url; }
    send() {}
    abort() { this.onabort(); }
    respond(value, status=200) { this.status=status;this.responseText=typeof value==='string'?value:JSON.stringify(value);this.onload(); }
  }
  const context = { document, innerWidth: 1280, innerHeight: 800, location: { search:'', reload() { reloads++; } },
    performance: { now: () => now }, Date, XMLHttpRequest: XHR,
    setTimeout(fn,delay) { const id=++nextId;timers.set(id,{fn,at:now+delay});return id; },
    clearTimeout(id) { timers.delete(id); }, setInterval(fn, delay) { context.tick=fn; }, module:{exports:{}} };
  context.window=context;
  vm.runInNewContext(source,context);
  return { context, requests, timers, nodes, get reloads() {return reloads;},
    advance(ms) {now+=ms;for (const [id,t] of Array.from(timers)) if(t.at<=now && timers.has(id)){timers.delete(id);t.fn();}context.tick();} };
}
const view = (extra={}) => ({ v:1,now:1791230000,rev:'1',build:'a',mode:'running',alert:null,
  focus:{state:'running',agent_label:'Codex',project:'p',title:'work',started_at:1791229900},
  counts:{active:1,waiting:0,done:0,projects:1},agents:[],queue:[],recent:[], ...extra });

test('malformed payload never refreshes freshness; returns through one retry', () => {
  const b=browser();
  b.requests[0].respond(view());
  assert.equal(b.context.document.body.className,'m-running');
  assert.equal(b.timers.size,1,'successful request clears watchdog');
  b.advance(3000);
  b.requests[1].respond(view({v:2}));
  b.advance(3000);
  b.requests[2].respond(view({focus:null}));
  b.advance(5000);
  b.requests[3].respond(view({queue:[null]}));
  b.advance(8000);
  assert.doesNotMatch(b.context.document.body.className,/lost/,'a few bad answers are not a lost link yet');
  b.requests[4].respond(view({queue:[null]}));
  b.advance(15000);
  b.requests[5].respond(view({queue:[null]}));
  b.advance(12000);
  assert.match(b.context.document.body.className,/lost/);
  b.advance(3000);
  b.requests[6].respond(view({rev:'2'}));
  assert.equal(b.context.document.body.className,'m-running');
  assert.equal(b.timers.size,1);
});

test('hung old WebView request aborts, goes offline, and recovers without manual reload', () => {
  const b=browser();
  b.advance(17001);
  assert.equal(b.requests.length,1);
  assert.equal(b.timers.size,1);
  b.advance(3000);
  assert.equal(b.requests.length,2);
  assert.doesNotMatch(b.context.document.body.className,/lost/,'one slow answer is not a lost link');
  b.advance(17001);
  b.advance(5000);
  assert.equal(b.requests.length,3);
  b.advance(4000);
  assert.match(b.context.document.body.className,/lost/);
  b.requests[2].respond(view());
  assert.equal(b.context.document.body.className,'m-running');
});

test('build change triggers unattended reload; repeated success has bounded timers', () => {
  const b=browser();
  b.requests[0].respond(view());
  for(let i=1;i<=100;i++) {b.advance(3000);b.requests[i].respond(view());assert.equal(b.timers.size,1);}
  b.advance(3000);b.requests[101].respond(view({build:'b'}));
  assert.equal(b.reloads,1);
});
