'use strict';

const calculator = window.RateWindowCalculator;
let rateData = null;
let timeMode = 'now';

const $ = id => document.getElementById(id);
const money = value => new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6
}).format(value);
const integer = value => new Intl.NumberFormat('en-US').format(value);

function formatUtc(date) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'UTC', year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23', timeZoneName: 'short'
  }).format(date);
}

function formatLocal(date) {
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit',
    second: '2-digit', timeZoneName: 'short'
  }).format(date);
}

function localInputValue(date) {
  const pad = value => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function tickClock() {
  const now = new Date();
  $('utc-clock').textContent = formatUtc(now);
  $('local-clock').textContent = formatLocal(now);
}

function setMode(mode) {
  timeMode = mode;
  const planned = mode === 'planned';
  $('use-now').classList.toggle('active', !planned);
  $('use-now').setAttribute('aria-pressed', String(!planned));
  $('use-planned').classList.toggle('active', planned);
  $('use-planned').setAttribute('aria-pressed', String(planned));
  $('planned-field').hidden = !planned;
  if (planned && !$('planned-time').value) $('planned-time').value = localInputValue(new Date());
}

function selectedTimestamp() {
  if (timeMode === 'now') return new Date().toISOString();
  const value = $('planned-time').value;
  if (!value) throw new Error('Choose a planned start time.');
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) throw new Error('The planned time is invalid.');
  return date.toISOString();
}

function readInteger(id, label) {
  const raw = $(id).value.trim();
  const value = Number(raw);
  if (!raw || !Number.isSafeInteger(value) || value < 0) throw new Error(`${label} must be a non-negative whole number.`);
  return value;
}

function requestFromForm() {
  return {
    timestamp: selectedTimestamp(),
    model: $('model').value,
    cache_hit: readInteger('cache-hit', 'Cache-hit tokens'),
    cache_miss: readInteger('cache-miss', 'Fresh input tokens'),
    output: readInteger('output', 'Output tokens')
  };
}

function waitLabel(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const parts = [];
  if (hours) parts.push(`${hours}h`);
  if (minutes || !hours) parts.push(`${minutes}m`);
  return parts.join(' ');
}

function setUnavailable(reason) {
  $('result-empty').hidden = true;
  $('result-content').hidden = true;
  $('result-unavailable').hidden = false;
  $('unavailable-reason').textContent = reason;
  $('result-status').textContent = 'Unavailable';
  $('result-status').className = 'status-pill warning';
}

function renderResult(result) {
  if (result.status !== 'ok') {
    setUnavailable(result.reason);
    return;
  }
  $('result-empty').hidden = true;
  $('result-unavailable').hidden = true;
  $('result-content').hidden = false;
  $('result-status').textContent = result.regime === 'peak' ? 'Peak rate' : 'Off-peak rate';
  $('result-status').className = `status-pill ${result.regime}`;
  $('selected-cost').textContent = money(result.cost);
  const totalTokens = result.tokens.cache_hit + result.tokens.cache_miss + result.tokens.output;
  $('selected-summary').textContent = `${integer(totalTokens)} total tokens at the ${result.regime.replace('_', '-')} USD schedule.`;
  $('selected-regime').textContent = result.regime === 'peak' ? 'Weekday peak' : 'Off-peak';
  const selectedDate = new Date(result.timestamp);
  $('selected-time').textContent = `${formatUtc(selectedDate)} · ${formatLocal(selectedDate)}`;
  $('basis-effective').textContent = formatUtc(new Date(result.effective_at));
  $('model-version').textContent = result.model_version;
  $('rate-hit').textContent = `${money(result.rates.cache_hit)} / 1M tokens`;
  $('rate-miss').textContent = `${money(result.rates.cache_miss)} / 1M tokens`;
  $('rate-output').textContent = `${money(result.rates.output)} / 1M tokens`;

  if (result.next_cheaper) {
    const next = result.next_cheaper;
    $('cheaper-panel').hidden = false;
    $('lowest-panel').hidden = true;
    $('next-cost').textContent = money(next.cost);
    $('savings').textContent = `${money(next.savings)} (${next.savings_percent.toFixed(1)}%)`;
    $('wait-time').textContent = waitLabel(next.wait_seconds);
    const nextDate = new Date(next.timestamp);
    $('next-summary').textContent = `At ${formatUtc(nextDate)} (${formatLocal(nextDate)}), the same token mix enters the ${next.regime.replace('_', '-')} band.`;
  } else {
    $('cheaper-panel').hidden = true;
    $('lowest-panel').hidden = false;
  }
}

function calculate(event) {
  if (event) event.preventDefault();
  $('form-error').textContent = '';
  if (!rateData) return;
  try {
    const result = calculator.calculate(rateData, requestFromForm());
    renderResult(result);
  } catch (error) {
    $('form-error').textContent = error.message;
  }
}

async function loadRates() {
  try {
    const response = await fetch('data/rates.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`Rate data returned HTTP ${response.status}.`);
    rateData = await response.json();
    window.__rateData = rateData;
    if (rateData.schema_version !== 1) throw new Error('Unsupported rate-data schema.');
    const basis = rateData.price_bases.find(item => item.status === 'current');
    if (!basis) throw new Error('No current declared rate basis is available.');
    $('model').replaceChildren(...basis.models.map(model => {
      const option = document.createElement('option');
      option.value = model.id;
      option.textContent = `${model.name} · ${model.version}`;
      return option;
    }));
    $('model').disabled = false;
    $('calculate').disabled = false;
    const asOf = new Date(rateData.current_as_of);
    const future = rateData.announced_future_bases.length;
    $('authority-clock').textContent = `${rateData.coverage_status === 'matched' ? 'EN + ZH matched' : 'source conflict'} · ${formatUtc(asOf)}${future ? ` · ${future} future basis` : ''}`;
    calculate();
  } catch (error) {
    $('authority-clock').textContent = 'Unavailable';
    setUnavailable(`Current source data could not be loaded: ${error.message}`);
  }
}

$('calculator-form').addEventListener('submit', calculate);
$('use-now').addEventListener('click', () => { setMode('now'); calculate(); });
$('use-planned').addEventListener('click', () => { setMode('planned'); calculate(); });
$('planned-time').addEventListener('change', calculate);
$('model').addEventListener('change', calculate);
for (const id of ['cache-hit', 'cache-miss', 'output']) $(id).addEventListener('change', calculate);
for (const button of document.querySelectorAll('[data-fixture]')) {
  button.addEventListener('click', () => {
    setMode('planned');
    $('planned-time').value = localInputValue(new Date(button.dataset.fixture));
    calculate();
  });
}

tickClock();
setInterval(tickClock, 1000);
setMode('now');
loadRates();
