const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/energy_optimizer/dashboard_static/app.js', 'utf8');

class Element {
  constructor(tag, registry) { this.tag = tag; this.registry = registry; this.children = []; this.attributes = {}; this.style = {}; this.classList = {add() {}}; }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  append(...children) { this.children.push(...children); }
  insertAdjacentHTML() {}
  addEventListener() {}
  replaceWith(element) { this.registry['#forecast-comparison'] = element; }
}
function setup() {
  const registry = {};
  const document = {createElement: tag => new Element(tag, registry), createElementNS: (_, tag) => new Element(tag, registry)};
  ['#forecast-run', '#forecast-run-meta', '#forecast-comparison'].forEach(id => registry[id] = new Element('div', registry));
  const context = vm.createContext({document, Date, Intl, Math, Number, svgNS:'svg',
    $: id => registry[id], safeText: String, localTime: String,
    number: value => String(value), isNumeric: value => typeof value === 'number' && Number.isFinite(value),
    definition: JSON.stringify, setState() {}, request: async () => null});
  vm.runInContext(source.slice(source.indexOf('function chartAxisTime('), source.indexOf('function makeEVTimeline(')), context);
  vm.runInContext(source.slice(source.indexOf('async function loadForecastComparison('), source.indexOf('function metricCard(')), context);
  return {context, registry};
}
function payload(start, actualCount = 21) {
  const from = Date.parse(start);
  return {available:true,forecast_type:'baseline_household_load',unit:'W',sample_count:actualCount,missing_actual_count:288-actualCount,excluded_actual_count:0,
    horizon_start_utc:start,horizon_end_utc:new Date(from+86400000).toISOString(),
    points:Array.from({length:288}, (_,i) => ({period_start_utc:new Date(from+i*300000).toISOString(),expected_value:1000+i,actual_value:i<actualCount?1100:null,lower_value:null,upper_value:null}))};
}
function descendants(element) { return [element, ...element.children.flatMap(descendants)]; }

test('selected run shows all 288 expected points, keeps missing actuals as gaps, and rebuilds dated time axis', async () => {
  const {context,registry} = setup();
  registry['#forecast-run'].value='1';
  context.request=async () => payload('2026-09-12T20:05:00Z');
  await context.loadForecastComparison();
  let nodes=descendants(registry['#forecast-comparison']);
  const lines=nodes.filter(n=>n.tag==='polyline');
  assert.equal(lines.find(n=>n.attributes.class==='series-0').attributes.points.split(' ').length,288);
  assert.equal(lines.find(n=>n.attributes.class==='series-1').attributes.points.split(' ').length,21);
  const ticks=nodes.filter(n=>n.tag==='text').map(n=>n.textContent);
  assert.match(ticks[0],/13.*06:05/);
  assert.match(ticks.at(-1),/14.*06:05/);
  registry['#forecast-run'].value='2';
  context.request=async () => payload('2026-09-12T22:35:00Z',0);
  await context.loadForecastComparison();
  nodes=descendants(registry['#forecast-comparison']);
  assert.equal(nodes.filter(n=>n.tag==='polyline').length,1);
  assert.match(nodes.find(n=>n.tag==='text').textContent,/08:35/);
  assert.notEqual(registry['#forecast-comparison'].children.length,0);
});

test('late response from previously selected run cannot overwrite new run',async()=>{
  const {context,registry}=setup();
  let resolveOld;
  registry['#forecast-run'].value='old';
  context.request=()=>new Promise(resolve=>{resolveOld=resolve;});
  const oldLoad=context.loadForecastComparison();
  registry['#forecast-run'].value='new';
  context.request=async()=>payload('2026-09-12T22:35:00Z');
  await context.loadForecastComparison();
  const current=registry['#forecast-comparison'];
  resolveOld(payload('2026-09-12T20:05:00Z'));
  await oldLoad;
  assert.equal(registry['#forecast-comparison'],current);
});

test('periodic run-list refresh preserves the selected older run', async () => {
  const {context, registry} = setup();
  vm.runInContext(source.slice(source.indexOf('async function loadForecastRuns('), source.indexOf('async function loadForecastComparison(')), context);
  const select=registry['#forecast-run'];
  select.dataset={}; select.value='older';
  Object.defineProperty(select,'innerHTML',{set(){this.value='newest';}});
  context.request=async (_key,path)=>path==='forecast-runs'
    ? {empty:false,runs:[{forecast_run_id:'newest'},{forecast_run_id:'older'}]}
    : payload('2026-09-12T20:05:00Z');
  await context.loadForecastRuns();
  assert.equal(select.value,'older');
});
