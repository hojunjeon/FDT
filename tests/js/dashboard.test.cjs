const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') {
    this.tag = tag; this.children = []; this.style = {}; this.value = '';
    this.classList = {add() {}, remove() {}};
  }
  addEventListener() {}
  append(...items) { this.children.push(...items); }
  appendChild(item) { this.append(item); return item; }
  replaceChildren(...items) { this.children = items; }
  querySelector() { return null; }
  setAttribute(key, value) { this[key] = value; }
  focus() {}
}
function setup(fetch) {
  const nodes = new Map();
  const context = vm.createContext({
    document: {
      querySelector: key => { if (!nodes.has(key)) nodes.set(key, new Element()); return nodes.get(key); },
      createElement: tag => new Element(tag),
      createElementNS: (_, tag) => new Element(tag),
      createTextNode: text => ({textContent: text}),
    },
    fetch, AbortController, setTimeout: () => 0, clearTimeout() {}, messages: [],
  });
  const script = fs.readFileSync(path.join(__dirname, '../../fdt/static/app.js'), 'utf8');
  vm.runInContext(script.replace(/\nboot\(\);\s*$/, '\n'), context);
  vm.runInContext('appendMessage = (...args) => messages.push(args);', context);
  return {run: script => vm.runInContext(script, context), context, nodes};
}
const response = payload => ({ok: true, json: async () => payload});
function deferred() { let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve}; }

test('missing values do not become zero money or risk', () => {
  const {run} = setup();
  for (const value of ['null', 'undefined', "''", "'  '", 'false', '{}', 'NaN']) {
    assert.equal(run(`money(${value})`), '자료 없음');
    assert.equal(run(`percent(${value})`), '자료 없음');
  }
  assert.equal(run('money(0)'), '0원');
  assert.equal(run('percent(0)'), '0%');
  assert.equal(run('percent(0.25)'), '25%');
  assert.equal(run("formatValue(0.25, 'percent')"), '25%');
});

test('late message cannot reactivate an ended session', async () => {
  const pending = deferred();
  const {run, context} = setup(url => url === '/api/chat/message' ? pending.promise : Promise.resolve(response({message: 'ended'})));
  run("state.profileId = 'A'; state.sessionId = 'old'; setActive(true);");
  const sent = run("sendMessage('hello')");
  await run('endConversation(true)');
  pending.resolve(response({message: 'stale reply'}));
  await sent;
  assert.equal(run('state.active'), false);
  assert.equal(run('state.sessionId'), null);
  assert.equal(run('state.sending'), false);
  assert.ok(!context.messages.some(item => item[1] === 'stale reply'));
});

test('old response cannot clear new session sending state', async () => {
  const pending = deferred();
  const {run} = setup(url => url === '/api/chat/message' ? pending.promise : Promise.resolve(response({})));
  run("state.profileId = 'A'; state.sessionId = 'old'; setActive(true);");
  const sent = run("sendMessage('hello')");
  await run('endConversation(true)');
  run("state.sessionId = 'new'; state.sending = true; setActive(true);");
  pending.resolve(response({message: 'old reply'}));
  await sent;
  assert.equal(run('state.sessionId'), 'new');
  assert.equal(run('state.sending'), true);
});

test('double start makes only one server request', async () => {
  const pending = deferred(); let count = 0;
  const {run} = setup(() => {count++; return pending.promise;});
  run("state.profileId = 'A';");
  const first = run('startConversation()');
  await run('startConversation()');
  assert.equal(count, 1);
  pending.resolve(response({session_id: 's', message: 'started'}));
  await first;
  assert.equal(run('state.sessionId'), 's');
  assert.equal(run('state.starting'), false);
});

test('cancelled start closes its orphaned server session', async () => {
  const pending = deferred(); const ended = [];
  const {run} = setup((url, options) => {
    if (url === '/api/chat/start') return pending.promise;
    ended.push(JSON.parse(options.body).session_id);
    return Promise.resolve(response({}));
  });
  run("state.profileId = 'A';");
  const first = run('startConversation()');
  await run('endConversation(true)');
  pending.resolve(response({session_id: 'orphan', message: 'started'}));
  await first;
  assert.deepEqual(ended, ['orphan']);
  assert.equal(run('state.sessionId'), null);
  assert.equal(run('state.active'), false);
});

test('out-of-order profile loads display only the newest selection', async () => {
  const a = deferred(); const b = deferred();
  const {run} = setup(url => url.includes('/A') ? a.promise : b.promise);
  const first = run("selectProfile('A')");
  await Promise.resolve(); await Promise.resolve();
  const second = run("selectProfile('B')");
  await Promise.resolve(); await Promise.resolve();
  b.resolve(response({profile: {id: 'B'}, state: {}}));
  await second;
  a.resolve(response({profile: {id: 'A'}, state: {}}));
  await first;
  assert.equal(run('state.profileId'), 'B');
  assert.equal(run('state.loading'), false);
});

test('forecast draws an accessible median and percentile band', () => {
  const {run} = setup();
  const chart = run("forecastChart([{low:-100,value:0,high:100}, {low:0,value:100,high:200}])");
  assert.equal(chart.tag, 'svg');
  assert.equal(chart.role, 'img');
  assert.deepEqual(Array.from(chart.children, child => child.tag), ['polygon', 'polyline']);
  assert.equal(run('forecastChart([{low:null,value:null,high:null}])'), null);
});
