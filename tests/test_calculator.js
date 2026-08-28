'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { calculate } = require('../frontend/calculator.js');

const project = path.resolve(__dirname, '..');
const data = JSON.parse(fs.readFileSync(path.join(project, 'data/rates.json'), 'utf8'));
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, 'cases.json'), 'utf8'));

function assertExpected(result, expected, id) {
  assert.strictEqual(result.status, expected.status, id);
  if (result.status !== 'ok') {
    assert(result.reason, `${id}: unavailable result lacks reason`);
    return;
  }
  assert.strictEqual(result.regime, expected.regime, id);
  assert(Math.abs(result.cost - expected.cost) < 1e-12, `${id}: cost ${result.cost}`);
  if (expected.next_cheaper === null && !expected.next_timestamp) assert.strictEqual(result.next_cheaper, null, id);
  if (expected.next_timestamp) {
    assert.strictEqual(result.next_cheaper.timestamp, expected.next_timestamp, id);
    assert(Math.abs(result.next_cheaper.cost - expected.next_cost) < 1e-12, id);
    assert.strictEqual(result.next_cheaper.wait_seconds, expected.wait_seconds, id);
    assert(Math.abs(result.next_cheaper.savings_percent - expected.savings_percent) < 1e-9, id);
  }
}

for (const testCase of cases) assertExpected(calculate(data, testCase.request), testCase.expected, testCase.id);

const conflict = structuredClone(data);
conflict.coverage_status = 'conflict';
assert.strictEqual(calculate(conflict, cases[0].request).status, 'unavailable');

const missing = structuredClone(data);
missing.price_bases[0].models[0].rates.off_peak.output = null;
assert.strictEqual(calculate(missing, cases[0].request).status, 'unavailable');

const futureData = structuredClone(data);
const future = structuredClone(futureData.price_bases[0]);
future.id = 'future-lower-test';
future.status = 'announced';
future.effective_at = '2026-09-01T02:30:00Z';
for (const model of future.models) {
  for (const band of Object.values(model.rates)) {
    for (const category of Object.keys(band)) band[category] /= 4;
  }
}
futureData.price_bases.push(future);
const futureResult = calculate(futureData, {
  timestamp: '2026-09-01T02:00:00Z', model: 'deepseek-v4-flash',
  cache_hit: 10000000, cache_miss: 1000000, output: 1000000
});
assert.strictEqual(futureResult.basis_id, 'deepseek-2026-08-16-banded');
assert.strictEqual(futureResult.next_cheaper.timestamp, '2026-09-01T02:30:00Z');
assert.strictEqual(futureResult.next_cheaper.basis_id, 'future-lower-test');
assert.strictEqual(futureResult.next_cheaper.cost, 0.475);

assert.throws(() => calculate(data, { ...cases[0].request, cache_hit: -1 }), /non-negative integer/);
assert.throws(() => calculate(data, { ...cases[0].request, timestamp: '2026-09-01T01:00:00' }), /offset/);
console.log(`JavaScript calculator passed ${cases.length} shared cases and 5 boundary/error checks`);
