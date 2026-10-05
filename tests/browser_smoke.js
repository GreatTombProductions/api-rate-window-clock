'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

(async () => {
  const base = process.env.SMOKE_BASE || 'http://127.0.0.1:8765/';
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('pageerror', error => errors.push(error.message));
  try {
    const response = await page.goto(base, { waitUntil: 'networkidle' });
    assert(response.ok(), `index returned ${response.status()}`);
    await page.waitForFunction(() => !document.getElementById('calculate').disabled);
    assert((await page.locator('#authority-clock').textContent()).includes('EN + ZH matched'));
    assert.strictEqual(await page.locator('#model option').count(), 2);
    assert((await page.locator('#model').textContent()).includes('DeepSeek-V4.1-Flash'));

    await page.locator('.fixtures summary').click();
    await page.locator('[data-fixture="2026-10-13T03:59:00Z"]').click();
    await page.waitForFunction(() => document.getElementById('selected-cost').textContent === '$1.56');
    assert.strictEqual((await page.locator('#result-status').textContent()).trim(), 'Peak rate');
    assert.strictEqual((await page.locator('#next-cost').textContent()).trim(), '$0.78');
    assert((await page.locator('#savings').textContent()).includes('$0.78 (50.0%)'));
    assert.strictEqual((await page.locator('#wait-time').textContent()).trim(), '1m');

    // holiday exclusion: undeclared peak carries the holiday alternative; declaring flips the band
    const caveat = page.locator('#holiday-caveat');
    assert(await caveat.isVisible(), 'holiday caveat hidden on a weekday peak start');
    assert((await caveat.textContent()).includes('2026-10-13') && (await caveat.textContent()).includes('$0.78'));
    assert((await page.locator('#holiday-label').textContent()).includes('Tuesday 2026-10-13'));
    await page.locator('#cn-holiday').check();
    await page.waitForFunction(() => document.getElementById('result-status').textContent === 'Off-peak rate');
    assert.strictEqual((await page.locator('#selected-cost').textContent()).trim(), '$0.78');
    assert((await caveat.textContent()).includes('Off-peak because you marked'));
    await page.locator('#cn-holiday').uncheck();
    await page.waitForFunction(() => document.getElementById('selected-cost').textContent === '$1.56');

    await page.locator('[data-fixture="2026-10-13T04:00:00Z"]').click();
    await page.waitForFunction(() => document.getElementById('result-status').textContent === 'Off-peak rate');
    assert.strictEqual((await page.locator('#selected-cost').textContent()).trim(), '$0.78');
    assert(await page.locator('#lowest-panel').isVisible());
    assert(await caveat.isHidden(), 'caveat shown outside a peak window');

    await page.locator('[data-fixture="2026-10-17T02:00:00Z"]').click();
    await page.waitForFunction(() => document.getElementById('selected-regime').textContent === 'Off-peak');
    assert((await page.locator('#selected-time').textContent()).includes('Oct'));

    for (const route of ['methodology.html', 'sources.html']) {
      const companion = await page.goto(base + route, { waitUntil: 'domcontentloaded' });
      assert(companion.ok(), `${route} returned ${companion.status()}`);
      assert(await page.locator('h1').isVisible(), `${route} has no visible h1`);
    }

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => !document.getElementById('calculate').disabled);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert(overflow <= 1, `mobile layout overflows by ${overflow}px`);
    assert(await page.locator('#calculator-form').isVisible());

    const conflictPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
    const data = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../data/rates.json'), 'utf8'));
    data.coverage_status = 'conflict';
    await conflictPage.route('**/data/rates.json', route => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(data)
    }));
    await conflictPage.goto(base, { waitUntil: 'networkidle' });
    await conflictPage.waitForFunction(() => document.getElementById('result-status').textContent === 'Unavailable');
    assert((await conflictPage.locator('#unavailable-reason').textContent()).includes('conflict'));
    await conflictPage.close();

    assert.deepStrictEqual(errors, []);
    console.log(`Browser smoke passed ${base}: current Flash rates, peak/off-peak boundaries, holiday caveat + declaration, weekend, source pages, conflict gate, 390px`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
