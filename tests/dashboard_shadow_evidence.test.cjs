const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/energy_optimizer/dashboard_static/app.js', 'utf8');

function setup(decision) {
  const registry = {};
  const context = vm.createContext({
    $: id => registry[id] ||= {innerHTML: ''}, setState() {},
    safeText: String, localTime: String, absolute: Math.abs,
    energy: value => value == null ? 'Unavailable' : `${value} kWh`,
    money: String, percent: String,
    request: async (_, resource) => resource === 'decisions/latest'
      ? {available: true, decision} : {empty: true},
  });
  vm.runInContext(source.slice(source.indexOf('function reserveMarginLabel('),
    source.indexOf('const chartDefinitions =')), context);
  return {context, registry};
}

function decision(version, margin, selected = 'HOLD') {
  return {selected_action: selected, status: 'completed', reason_codes_json: [],
    input_snapshot_json: version ? {calculation_version: version} : {},
    candidates: [{action: 'HOLD', feasible: true, reserve_margin_after_kwh: margin,
      blocking_constraints_json: [], warning_constraints_json: []}]};
}

test('new HOLD presents a signed shortfall and calculation version', async () => {
  const {context, registry} = setup(decision('battery-shadow-evidence-v2', -14.4));
  await context.loadDecisions();
  assert.match(registry['#decision-current'].innerHTML, /Reserve margin/);
  assert.match(registry['#decision-current'].innerHTML, /-14.4 kWh/);
  assert.match(registry['#decision-current'].innerHTML, /battery-shadow-evidence-v2/);
  assert.doesNotMatch(registry['#decision-candidates'].innerHTML, /legacy clamped/);
});

test('historical HOLD keeps stored zero and explicitly labels clamped available energy', async () => {
  const historical = decision(null, 0);
  const before = JSON.stringify(historical);
  const {context, registry} = setup(historical);
  await context.loadDecisions();
  assert.match(registry['#decision-current'].innerHTML, /Legacy available energy \(clamped\)/);
  assert.match(registry['#decision-current'].innerHTML, /0 kWh/);
  assert.match(registry['#decision-candidates'].innerHTML, /legacy clamped available energy/);
  assert.equal(JSON.stringify(historical), before);
});

test('missing margin and blocked no-selection are unavailable without invented HOLD', async () => {
  const {context, registry} = setup(decision('battery-shadow-evidence-v2', null, null));
  await context.loadDecisions();
  assert.match(registry['#decision-current'].innerHTML, /No recommendation/);
  assert.match(registry['#decision-current'].innerHTML, /Unavailable/);
});

test('unrecognised calculation marker cannot claim evidence-v2 margin semantics', async () => {
  const {context, registry} = setup(decision('unknown-calculation', 0));
  await context.loadDecisions();
  assert.match(registry['#decision-current'].innerHTML, /unrecognised calculation/);
  assert.match(registry['#decision-candidates'].innerHTML, /semantics unavailable/);
  assert.doesNotMatch(registry['#decision-current'].innerHTML, />Reserve margin</);
});
