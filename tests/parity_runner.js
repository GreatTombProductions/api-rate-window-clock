'use strict';
const fs = require('fs');
const { calculate } = require('../frontend/calculator.js');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(payload.requests.map(request => calculate(payload.data, request))));
