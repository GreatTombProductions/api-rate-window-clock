'use strict';
const fs = require('fs');
// Source checkout keeps the page in frontend/; the published repository serves it from the root.
const { calculate } = require(require('fs').existsSync(require('path').join(__dirname, '../frontend/calculator.js')) ? '../frontend/calculator.js' : '../calculator.js');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(payload.requests.map(request => calculate(payload.data, request))));
