const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/energy_optimizer/dashboard_static/app.js', 'utf8');

test('live card explains pending scores and omits unavailable bound columns', async () => {
  const target = {innerHTML:'', insertAdjacentHTML(_where, text) {this.innerHTML += text;}, append() {}};
  const registry = {'#forecast-card-content':target, '#forecast-card-mode':{value:'live'}};
  let chart;
  const context = vm.createContext({Date, Number, Math, Intl,
    $: selector => registry[selector], safeText: String, localTime: String,
    percent: String, power: String, energy: String, definition: JSON.stringify,
    makeChart: (...args) => {chart=args; return {};},
    request: async () => ({
      metrics:{period_label:'Compared elapsed period'}, identity:{}, calibration_status:'provisional',
      coverage:{eligible_actual_intervals:1,matured_intervals:3,matured_actual_coverage_percent:33.3,observed_pending_score_intervals:1},
      uncertainty_status:'not_available_for_model', period_start_utc:'2026-10-04T21:35:00Z',period_end_utc:'2026-10-05T21:35:00Z',now_utc:'2026-10-04T21:50:00Z',
      points:[{period_start_utc:'2026-10-04T21:35:00Z',forecast_w:1234,actual_w:2287,actual_eligible:true,actual_source:'observations_pending_score'},
        {period_start_utc:'2026-10-04T21:40:00Z',forecast_w:1200,actual_w:null,actual_eligible:false,exclusion_reason:'known_ev_session_without_ac_power'}],
    }),
  });
  vm.runInContext(source.slice(source.indexOf('async function loadForecastActualCard('), source.indexOf('function reserveMarginLabel(')), context);
  await context.loadForecastActualCard();
  assert.match(target.innerHTML, /official scoring pending/);
  assert.match(target.innerHTML, /Uncertainty bounds are not available/);
  assert.match(target.innerHTML, /1 of 3 completed intervals/);
  assert.equal(chart[2].length, 2);
  assert.equal(chart[3][0].actual, 2287);
  assert.equal(chart[3][1].actual_missing_reason, 'known_ev_session_without_ac_power');
});

test('actual absence reasons are readable and displayed negative zero is normalised', () => {
  const context=vm.createContext({Number,Math});
  vm.runInContext(source.slice(source.indexOf('function actualReason('),source.indexOf('function makeChart(')),context);
  vm.runInContext(source.slice(source.indexOf('function number('),source.indexOf('function age(')),context);
  assert.equal(context.missingChartValue({actual_missing_reason:'future_interval'},'actual'),'Future interval');
  assert.match(context.actualReason('known_ev_session_without_ac_power'), /EV charging/);
  assert.equal(context.number(-0.00001,2),'0');
  assert.equal(context.number(-1.25,2),'-1.25');
});
