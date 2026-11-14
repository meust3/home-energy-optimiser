const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/energy_optimizer/dashboard_static/app.js', 'utf8');
const weather = fs.readFileSync('src/energy_optimizer/dashboard_static/weather.js', 'utf8');
const pages = ['overview', 'history', 'forecasts', 'forecast-operations', 'calibration',
  'solar-diagnostics', 'reserve', 'arbitrage', 'decisions', 'data-quality'];
const flush = () => new Promise(resolve => setImmediate(resolve));

function setup(script = source, storageBlocked = false) {
  const nodes = new Map();
  function element(id = '') {
    return {id, value: '', dataset: {}, innerHTML: '', textContent: '', className: '',
      children: [], events: {}, attributes: {}, style: {},
      setAttribute(k, v) {this.attributes[k] = v;},
      addEventListener(k, cb) {this.events[k] = cb;},
      querySelector() {return null;},
      append(...items) {this.children.push(...items);},
      replaceChildren(...items) {this.children = items;},
      insertAdjacentHTML(_where, text) {this.innerHTML += text;}};
  }
  const node = id => {if (!nodes.has(id)) nodes.set(id, element(id.slice(1))); return nodes.get(id);};
  const calls = [];
  const document = {baseURI:'https://example.invalid/ingress/test/', hidden:false, events:{},
    querySelector:node, getElementById:id => node('#' + id), createElement:() => element(),
    querySelectorAll:selector => selector === '.page' ? pages.map(id => node('#' + id)) : [],
    addEventListener(k, cb) {this.events[k] = cb;}};
  const context = vm.createContext({document, URL, AbortController, Date, Intl, console,
    location:{hash:''}, window:{addEventListener() {}},
    localStorage:{getItem() {if (storageBlocked) throw new Error('Storage blocked'); return null;},
      setItem() {if (storageBlocked) throw new Error('Storage blocked');}},
    setInterval() {}, clearInterval() {},
    fetch(url, options) {
      return new Promise((resolve, reject) => {
        calls.push({url, options, resolve, reject});
        options.signal.addEventListener('abort', () => reject(options.signal.reason));
      });
    }});
  vm.runInContext(script, context);
  return {context, document, calls, node};
}

test('all ten dashboard pages load, cancellation stays quiet, and visibility resumes loaded screens', async () => {
  const {context, document, calls, node} = setup();
  for (const page of pages) {
    context.location.hash = '#' + page;
    context.activateTab();
    assert.equal(node('#' + page).hidden, false);
    assert.equal(pages.filter(id => !node('#' + id).hidden).length, 1);
  }
  const before = new Set(calls.map(call => call.url.pathname));
  assert.ok(before.has('/ingress/test/api/v1/forecast-accuracy'));
  assert.ok(before.has('/ingress/test/api/v1/arbitrage'));
  document.hidden = true;
  document.events.visibilitychange();
  await flush();
  for (const id of ['overview', 'history', 'forecast', 'operations', 'calibration', 'solar', 'reserve', 'decisions', 'quality', 'arbitrage']) {
    assert.doesNotMatch(node('#' + id + '-state').textContent, /abort/i);
    assert.doesNotMatch(node('#' + id + '-state').className, /error-state/);
  }
  const count = calls.length;
  document.hidden = false;
  document.events.visibilitychange();
  const after = new Set(calls.slice(count).map(call => call.url.pathname));
  assert.deepEqual(after, before);
});

test('blocked browser storage does not prevent startup or changing card mode', () => {
  const {calls, node} = setup(source, true);
  assert.ok(calls.length > 0);
  assert.doesNotThrow(() => node('#forecast-card-mode').events.change());
});

test('skip link and unknown hashes never hide every dashboard page', () => {
  const {context, node} = setup();
  for (const hash of ['#main', '#does-not-exist', '#latest-data']) {
    context.location.hash = hash;
    context.activateTab();
    assert.equal(node('#overview').hidden, false);
  }
});

test('superseded response body cannot overwrite a newer request', async () => {
  const {context, calls} = setup();
  const old = context.request('test', 'timeseries');
  const oldRejected = assert.rejects(old, {name:'AbortError'});
  let releaseBody;
  calls.at(-1).resolve({ok:true, json:() => new Promise(resolve => {releaseBody = resolve;})});
  await flush();
  const current = context.request('test', 'timeseries');
  calls.at(-1).resolve({ok:true, json:async () => ({version:'current'})});
  assert.equal((await current).version, 'current');
  releaseBody({version:'old'});
  await oldRejected;
});

test('real Forecast Operations failures remain visible', async () => {
  const {context, calls, node} = setup();
  const loading = context.loadForecastOperations();
  calls.find(call => call.url.pathname.endsWith('/forecast-accuracy')).resolve({
    ok:false, json:async () => ({error:{message:'Stored accuracy is unavailable.'}})});
  await loading;
  assert.equal(node('#operations-state').textContent, 'Stored accuracy is unavailable.');
  assert.match(node('#operations-state').className, /error-state/);
});

test('accuracy does not join overlapping versions and keeps predictions when actuals are excluded', async () => {
  const {context, node} = setup();
  const charts = [];
  context.makeChart = (...args) => {charts.push(args); return {};};
  context.request = async (_key, path) => {
    if (path === 'forecast-operations/status') return {enabled:false};
    if (path === 'forecast-runs') return {runs:[]};
    return {available:true, metrics:{}, by_horizon:{}, by_local_hour:{}, by_day_type:{},
      by_model_version:{}, by_forecast_type:{},
      points:[{period_start_utc:'2026-11-14T00:00:00Z', expected_value:1500,
        actual_value:2000, health_eligible:false, missing_reason:'actual_unhealthy_or_ineligible'}]};
  };
  await context.loadForecastOperations();
  assert.equal(charts.length, 0);
  assert.match(node('#accuracy-content').innerHTML, /Select one forecast run/);
  node('#accuracy-run').value = '1';
  await context.loadForecastOperations();
  assert.equal(charts.length, 1);
  assert.equal(charts[0][3][0].series_available.expected, true);
  assert.equal(charts[0][3][0].series_available.actual, false);
  assert.equal(charts[0][3][0].expected, 1500);
});

test('accuracy discloses a saturated bounded query without claiming full-range coverage', async () => {
  const {context, node} = setup();
  const accuracy = {available:true, metrics:{coverage_percent:100}, by_horizon:{},
    by_local_hour:{}, by_day_type:{}, by_model_version:{}, by_forecast_type:{},
    points:Array.from({length:2500}, () => ({period_start_utc:'2026-11-14T00:00:00Z'}))};
  context.request = async (_key, path) => path === 'forecast-operations/status'
    ? {enabled:true} : path === 'forecast-runs' ? {runs:[]} : accuracy;
  await context.loadForecastOperations();
  assert.match(node('#accuracy-content').innerHTML, /2,500-point query limit was reached/);
  assert.match(node('#accuracy-content').innerHTML, /may not cover the full selected range/);
  accuracy.points = accuracy.points.slice(0, 288);
  await context.loadForecastOperations();
  assert.doesNotMatch(node('#accuracy-content').innerHTML, /query limit was reached/);
  assert.match(node('#accuracy-content').innerHTML, /Returned forecast points: 288/);
  assert.match(node('#accuracy-content').innerHTML, /within this returned set/);
});

test('weather archive reports the bounded list and prevents stale selection responses', async () => {
  const {context, calls, node} = setup(weather);
  const first = calls[0];
  node('#weather-cycle').value = 'new';
  const loading = context.readArchive();
  calls.at(-1).resolve({ok:true, json:async () => ({collection:{status:'COMPLETE'},
    cycles:[{id:'new', created_at:'2026-11-14T00:00:00Z', status:'COMPLETE'}],
    selected:{cycle_id:'new', status:'COMPLETE', window_start:'start', window_end:'end', targets:[]}})});
  await loading;
  await flush();
  assert.equal(first.options.signal.aborted, true);
  assert.match(node('#weather-status').textContent, /Showing 1 recent cycles.*not the total archive count/);
  assert.equal(node('#weather-cycle').children[0].value, 'new');
  assert.equal(node('#weather-cycle').children[0].selected, true);
});
