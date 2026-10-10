const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/energy_optimizer/dashboard_static/app.js', 'utf8');

async function render(item) {
  const registry = {};
  const requests = [];
  const context = vm.createContext({
    $: id => registry[id] ||= {innerHTML: ''}, setState() {},
    safeText: String, localTime: String, age: String, money: String, energy: String,
    definition: rows => JSON.stringify(rows),
    request: async (...args) => {requests.push(args); return {items:[item], status:item.status, execution:'disabled'};},
  });
  vm.runInContext(source.slice(source.indexOf('async function loadArbitrage()'),
    source.indexOf('function activateTab()')), context);
  await context.loadArbitrage();
  assert.equal(requests.length, 1);
  return registry['#arbitrage-content'].innerHTML;
}

test('persisted modes, full-capacity restriction and conditional EV basis are visible', async () => {
  const item = {status:'research_only', selected:'HOLD', research_load_basis:'baseline + frozen zero additional EV; not measured absence',
    input_semantics:{price_mode:'conditional_amber_boundary_start_plus_one_v1', full_capacity_floor:true,
      reserve_binding:{mode:'linked_capacity_capped_reserve_v1',source_field:'capacity_capped_reserve_kwh',snapshot_sha256:'authored-hash'}}};
  const before = JSON.stringify(item);
  const html = await render(item);
  assert.match(html, /conditional_amber_boundary_start_plus_one_v1/);
  assert.match(html, /linked_capacity_capped_reserve_v1/);
  assert.match(html, /no permitted model discharge/);
  assert.match(html, /not measured absence/);
  assert.equal(JSON.stringify(item), before);
});

test('old blocked records retain explicit legacy modes without invented economics', async () => {
  const html = await render({status:'blocked',selected:'HOLD',load_basis:'baseline requires scenario'});
  assert.match(html, /Legacy strict\/raw/);
  assert.match(html, /Legacy fixed research floor/);
  assert.match(html, /Unavailable/);
});
