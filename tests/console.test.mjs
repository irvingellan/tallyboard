import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const read = name => readFileSync(new URL(`../tallyboard/static/${name}`, import.meta.url), 'utf8');
const source = read('console.js');
const sandbox = { module: { exports: {} } };
vm.runInNewContext(source, sandbox);
const fc = sandbox.module.exports;
fc.setLang('pt-BR');  // the assertions below were written against the Portuguese wording

test('the page stays inside what an Android 5.1 WebView parses', () => {
  const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/'(?:[^'\\\n]|\\.)*'/g, "''");
  for (const [name, pattern] of Object.entries({
    'arrow function': /=>/, 'let/const': /\b(?:let|const)\s/, 'template string': /`/, class: /\bclass\s/,
    'async/await': /\b(?:async|await)\s/, spread: /\.\.\./, fetch: /\bfetch\(/, 'optional chaining': /\?\./,
    'nullish coalescing': /\?\?/, 'for-of': /\bfor\s*\([^)]*\bof\b/,
  })) assert.equal(pattern.test(code), false, `${name} is not supported by the tablet`);
  const css = read('console.css').replace(/\/\*[\s\S]*?\*\//g, '');
  for (const pattern of [/var\(--/, /display:\s*grid/, /\bgap:/, /clamp\(/, /position:\s*sticky/, /\binset:/])
    assert.equal(pattern.test(css), false, `${pattern} is not supported by the tablet`);
});

test('the page is read-only and loads nothing from the internet', () => {
  // the only writes: a tap brings a session forward, a hold waves one off the list
  assert.deepEqual(source.match(/\.open\('[A-Z]+', [^)]*/g), [".open('GET', '/api/state?t=' + Date.now(", ".open('POST', path + '?id=' + encodeURIComponent(id"]);
  assert.deepEqual(source.match(/send\('\/api\/[a-z]+'/g), ["send('/api/dismiss'", "send('/api/focus'"]);
  assert.equal(/https?:\/\//.test(source + read('index.html') + read('console.css')), false);
});

test('the page formats time for reading at a distance', () => {
  assert.equal(fc.timer(754), '12:34');
  assert.equal(fc.timer(3 * 3600 + 5 * 60), '3h 05m');
  assert.equal(fc.timer(-4), '00:00');
  assert.deepEqual([30, 150, 7300, 200000].map(fc.ago), ['agora', 'há 2 min', 'há 2 h', 'há 2 d']);
  assert.deepEqual([45, 1085, 3900].map(fc.duration), ['45 s', '18 min', '1 h 05']);
  const noonUtc = Date.UTC(2026, 9, 5, 12, 7);
  assert.equal(fc.clock(noonUtc), '12:07');
  assert.equal(fc.dateLine(noonUtc), 'segunda-feira, 5 de outubro');
  assert.equal(fc.isNight(Date.UTC(2026, 9, 5, 23, 30)), true);
  assert.equal(fc.isNight(noonUtc), false);
});

test('the page only shows facts the source reported', () => {
  const bare = { started_at: null, branch: null, checks: null, files_changed: null };
  assert.equal(fc.metaCells(bare, 'running', 0).length, 0);
  const cells = fc.metaCells({ started_at: 43200, branch: 'main', checks: { passed: 3, failed: 1, total: 4 }, files_changed: 2 }, 'running', 0);
  assert.deepEqual(Array.from(cells, c => `${c.k}=${c.v}`), ['Início=12:00', 'Branch=main', 'Checks=1 de 4 falharam', 'Arquivos=2']);
  assert.equal(fc.checksText({ passed: 4, failed: 0, total: 4 }), '4/4 ok');
  assert.equal(fc.focusClock({ blocked_since: 100 }, 'blocked', 352).text, '04:12');
  assert.equal(fc.focusClock({ started_at: null }, 'running', 352).text, '');
});

test('the page escapes agent-supplied text and counts down a finished job', () => {
  const html = fc.rowsHtml([{ state: 'running', agent_label: 'Claude', project: '<img onerror=x>', title: '"t"', started_at: 1 }], true);
  assert.equal(html.includes('<img'), false);
  assert.match(html, /&lt;img onerror=x&gt;/);
  assert.match(fc.agentsHtml([{ state: 'idle', label: 'Gemini', jobs: 0 }]), /s-idle.*ocioso.*Gemini/);
  assert.equal(fc.expireFraction({ focus: { ended_at: 100 }, focus_expires_at: 400 }, 250), 0.5);
  assert.equal(fc.expireFraction({ focus: { ended_at: 100 }, focus_expires_at: null }, 250), 0);
});

test('the page words server phrase codes in the chosen language and falls back to English', () => {
  assert.equal(fc.setLang('xx'), 'en');
  assert.equal(fc.say('@editing:state.py'), 'Editing state.py');
  assert.equal(fc.say('@permission'), 'Asks permission to use a tool');
  assert.equal(fc.say('@permission:Bash'), 'Asks permission to use Bash');
  assert.equal(fc.say('Run the tests'), 'Run the tests');
  assert.equal(fc.say('@never_heard_of:x'), 'x');
  assert.equal(fc.say(null), '');
  assert.equal(fc.ago(150), '2 min ago');
  assert.equal(fc.dateLine(Date.UTC(2026, 9, 5, 12, 7)), 'Monday, October 5');
  assert.equal(fc.setLang('pt-BR'), 'pt-BR');
  assert.equal(fc.say('@err_model:x-1'), 'Modelo x-1 não disponível nesta conta');
  assert.equal(fc.say('@week'), '');
});
