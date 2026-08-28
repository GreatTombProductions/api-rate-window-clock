'use strict';

(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.RateWindowCalculator = api;
})(typeof self !== 'undefined' ? self : this, function () {
  const TOKEN_FIELDS = ['cache_hit', 'cache_miss', 'output'];

  function parseTimestamp(value) {
    if (typeof value !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/i.test(value.trim())) {
      throw new Error('timestamp must include an offset');
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) throw new Error('timestamp is invalid');
    return parsed;
  }

  function iso(date) {
    return date.toISOString().replace('.000Z', 'Z');
  }

  function basisAt(data, timestamp) {
    return data.price_bases
      .filter(basis => parseTimestamp(basis.effective_at) <= timestamp)
      .sort((a, b) => parseTimestamp(b.effective_at) - parseTimestamp(a.effective_at))[0] || null;
  }

  function minutes(value) {
    const [hour, minute] = value.split(':').map(Number);
    return hour * 60 + minute;
  }

  function regime(basis, timestamp) {
    const jsWeekday = timestamp.getUTCDay();
    const isoWeekday = jsWeekday === 0 ? 7 : jsWeekday;
    const minute = timestamp.getUTCHours() * 60 + timestamp.getUTCMinutes();
    if (basis.schedule.peak_weekdays.includes(isoWeekday)) {
      for (const window of basis.schedule.peak_windows) {
        if (minutes(window.start) <= minute && minute < minutes(window.end)) return 'peak';
      }
    }
    return 'off_peak';
  }

  function modelAt(basis, modelId) {
    return basis.models.find(model => model.id === modelId) || null;
  }

  function round(value, digits) {
    return Number(value.toFixed(digits));
  }

  function costAt(data, timestamp, modelId, tokens) {
    const basis = basisAt(data, timestamp);
    if (!basis) return null;
    const model = modelAt(basis, modelId);
    if (!model) return null;
    const band = regime(basis, timestamp);
    const rates = model.rates[band];
    if (!rates || TOKEN_FIELDS.some(field => rates[field] === null || rates[field] === undefined)) return null;
    const total = TOKEN_FIELDS.reduce((sum, field) => sum + tokens[field] * rates[field], 0) / data.unit_tokens;
    return {
      basis_id: basis.id,
      effective_at: basis.effective_at,
      regime: band,
      model_version: model.version,
      rates: Object.fromEntries(TOKEN_FIELDS.map(field => [field, rates[field]])),
      cost: round(total, 12)
    };
  }

  function candidateBoundaries(data, timestamp) {
    const candidates = new Set();
    const midnight = Date.UTC(timestamp.getUTCFullYear(), timestamp.getUTCMonth(), timestamp.getUTCDate());
    for (let offset = 0; offset < 10; offset += 1) {
      const day = midnight + offset * 86400000;
      candidates.add(day);
      candidates.add(day + 86400000);
      for (const basis of data.price_bases) {
        for (const window of basis.schedule.peak_windows) {
          for (const edge of [window.start, window.end]) candidates.add(day + minutes(edge) * 60000);
        }
      }
    }
    for (const basis of data.price_bases) candidates.add(parseTimestamp(basis.effective_at).getTime());
    const lower = timestamp.getTime();
    const upper = lower + 8 * 86400000;
    return [...candidates].filter(value => lower < value && value <= upper).sort((a, b) => a - b).map(value => new Date(value));
  }

  function calculate(data, request) {
    const timestamp = parseTimestamp(request.timestamp);
    const modelId = String(request.model);
    const tokens = {};
    for (const field of TOKEN_FIELDS) {
      const value = request[field];
      if (!Number.isSafeInteger(value) || value < 0) throw new Error(`${field} must be a non-negative integer`);
      tokens[field] = value;
    }
    const unavailable = { status: 'unavailable', timestamp: iso(timestamp), model: modelId, tokens };
    if (data.coverage_status !== 'matched') {
      return { ...unavailable, reason: 'Authority surfaces conflict or are unavailable.' };
    }
    const selected = costAt(data, timestamp, modelId, tokens);
    if (!selected) {
      return { ...unavailable, reason: 'No complete declared rate basis covers this model and timestamp.' };
    }

    let nextCheaper = null;
    for (const candidate of candidateBoundaries(data, timestamp)) {
      const compared = costAt(data, candidate, modelId, tokens);
      if (compared && compared.cost < selected.cost - 1e-15) {
        const savings = selected.cost - compared.cost;
        nextCheaper = {
          timestamp: iso(candidate),
          basis_id: compared.basis_id,
          regime: compared.regime,
          cost: compared.cost,
          savings: round(savings, 12),
          savings_percent: round(selected.cost ? savings / selected.cost * 100 : 0, 9),
          wait_seconds: Math.floor((candidate - timestamp) / 1000)
        };
        break;
      }
    }
    return { status: 'ok', timestamp: iso(timestamp), model: modelId, tokens, ...selected, next_cheaper: nextCheaper };
  }

  return { calculate, parseTimestamp, regime };
});
