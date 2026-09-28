'use strict';

// Executes the Code-node JavaScript embedded in workflow.json against the live
// target site, emulating the n8n runtime helpers ($, $input, $now, $execution).

const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');

const WORKFLOW_PATH = path.resolve(__dirname, '..', 'workflow.json');
const TARGET_URL = 'https://webscraper.io/test-sites/e-commerce/static/computers/laptops';
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

const workflow = JSON.parse(fs.readFileSync(WORKFLOW_PATH, 'utf8'));
const codeByNode = Object.fromEntries(
  workflow.nodes.filter((n) => n.type === 'n8n-nodes-base.code').map((n) => [n.name, n.parameters.jsCode]),
);

const nodeOutputs = new Map();
const nowStub = {
  toISO: () => new Date().toISOString(),
};

const toItems = (jsonList) => jsonList.map((json) => ({ json }));

const selector = (name) => {
  if (!nodeOutputs.has(name)) throw new Error(`Node "${name}" has not produced output yet`);
  const items = nodeOutputs.get(name);
  return { first: () => items[0], last: () => items[items.length - 1], all: () => items };
};

async function runCodeNode(name, inputItems) {
  const code = codeByNode[name];
  assert.ok(code, `Code node "${name}" missing from workflow.json`);
  const input = { first: () => inputItems[0], last: () => inputItems[inputItems.length - 1], all: () => inputItems };
  const fn = new AsyncFunction('$', '$input', '$now', '$execution', code);
  const result = await fn(selector, input, nowStub, { id: 'sim-1001' });
  assert.ok(Array.isArray(result), `Code node "${name}" must return an array`);
  nodeOutputs.set(name, result);
  return result;
}

async function fetchPage(page) {
  const response = await fetch(`${TARGET_URL}?page=${page}`, {
    headers: { 'User-Agent': 'NuredermPriceMonitor-Test/1.0' },
  });
  return [{ json: { statusCode: response.status, statusMessage: response.statusText, headers: {}, data: await response.text() } }];
}

async function scrapeAllPages() {
  nodeOutputs.set('Workflow Config', toItems([{
    maxPages: 50,
    requestDelaySeconds: 1,
    priceAnomalyThresholdPct: 20,
    telegramChatId: 'test',
    googleSheetId: 'test',
    historySheetName: 'price_history',
  }]));

  let state = await runCodeNode('Init Pagination State', []);
  for (;;) {
    nodeOutputs.set('Pagination State', state);
    const http = await fetchPage(state[0].json.page);
    assert.ok(http[0].json.statusCode >= 200 && http[0].json.statusCode < 300, `HTTP ${http[0].json.statusCode}`);
    const [parsed] = await runCodeNode('Parse & Normalize Page', http);
    assert.equal(parsed.json.status, 'ok', `Page ${parsed.json.page} unhealthy: ${parsed.json.reason}`);
    if (!(parsed.json.hasNextPage && parsed.json.page < parsed.json.maxPages)) return parsed;
    state = await runCodeNode('Advance Page', [parsed]);
  }
}

async function main() {
  const lastPage = await scrapeAllPages();
  console.log(`Pagination finished at page ${lastPage.json.page} (detected ${lastPage.json.totalPagesDetected}), ` +
    `${lastPage.json.products.length} unique products`);
  assert.equal(lastPage.json.hasNextPage, false, 'Loop must exit because the last page has no rel="next"');
  assert.equal(lastPage.json.page, lastPage.json.totalPagesDetected);

  const [snapshot] = await runCodeNode('Finalize Snapshot', [lastPage]);
  const products = snapshot.json.products;
  assert.ok(products.length > 100, `Expected >100 laptops, got ${products.length}`);

  for (const product of products) {
    assert.equal(typeof product.price, 'number', `price must be numeric for ${product.title}`);
    assert.ok(Number.isFinite(product.price) && product.price > 0);
    assert.ok(Number.isInteger(product.review_count) && product.review_count >= 0);
    assert.match(product.url, /^https:\/\/webscraper\.io\/test-sites\/e-commerce\/static\/product\/\d+$/);
    assert.ok(product.title.length > 0);
    assert.match(product.scraped_at, /^\d{4}-\d{2}-\d{2}T/);
  }
  const packard = products.find((p) => p.title === 'Packard 255 G2');
  assert.ok(packard, 'Known product "Packard 255 G2" must be extracted');
  assert.equal(packard.price, 416.99, '"$416.99" must sanitize to float 416.99');
  console.log('Sample product:', JSON.stringify(packard));

  // Baseline run: empty sheet -> n8n alwaysOutputData yields one empty item.
  const baseline = await runCodeNode('Detect Price Changes', [{ json: {} }]);
  assert.equal(baseline.length, products.length);
  assert.ok(baseline.every((i) => i.json.change_type === 'NEW' && i.json.is_baseline_run === true));

  // Follow-up run: history holds an older and a newer row per product; mutate a few prices.
  const history = [];
  for (const [index, product] of products.entries()) {
    history.push({ json: { product_id: product.product_id, price: '1.00', scraped_at: '2026-01-01T09:00:00.000+03:00' } });
    if (index === 0) continue; // product 0 keeps only the stale $1.00 row
    let price = product.price;
    if (index === 1) price = product.price + 100; // current is lower -> PRICE_DOWN, anomaly
    if (index === 2) price = +(product.price - 1).toFixed(2); // current is higher -> PRICE_UP, small
    history.push({ json: { product_id: product.product_id, price: String(price), scraped_at: '2026-09-27T09:00:00.000+03:00' } });
  }
  history.push({ json: { product_id: products[3].product_id, price: 'not-a-price', scraped_at: '2026-09-28T00:00:00.000+03:00' } });

  const diff = (await runCodeNode('Detect Price Changes', history)).map((i) => i.json);
  const byId = Object.fromEntries(diff.map((row) => [row.product_id, row]));
  assert.equal(byId[products[0].product_id].change_type, 'PRICE_UP', 'Only the old $1.00 row exists for product 0');
  assert.equal(byId[products[1].product_id].change_type, 'PRICE_DOWN');
  assert.equal(byId[products[1].product_id].is_anomaly, true);
  assert.equal(byId[products[2].product_id].change_type, 'PRICE_UP');
  assert.equal(byId[products[2].product_id].price_delta, 1);
  assert.equal(byId[products[3].product_id].change_type, 'UNCHANGED', 'Malformed history rows must be ignored');

  const changed = diff.filter((r) => r.change_type !== 'UNCHANGED' && r.is_baseline_run === false);
  const [alert] = await runCodeNode('Build Alert Message', toItems(changed));
  assert.ok(alert.json.text.length <= 4000);
  assert.equal(alert.json.changeCount, 3);
  console.log(`\nAlert message (${alert.json.changeCount} changes, ${alert.json.anomalyCount} anomalies):\n${alert.json.text}\n`);

  // Failure path: an out-of-range page answers HTTP 200 but contains zero laptops.
  nodeOutputs.set('Pagination State', toItems([{ page: 99, maxPages: 50, pagesFetched: 4, runId: 'sim-1001', products: [] }]));
  const [bad] = await runCodeNode('Parse & Normalize Page', await fetchPage(99));
  assert.equal(bad.json.status, 'error');
  assert.match(bad.json.reason, /^ZERO_PRODUCTS/);
  const [failure] = await runCodeNode('Build Failure Payload', [bad]);
  assert.equal(failure.json.stage, 'EXTRACTION');
  const [transport] = await runCodeNode('Build Failure Payload', [{ json: { error: 'getaddrinfo ENOTFOUND webscraper.io' } }]);
  assert.equal(transport.json.stage, 'HTTP_TRANSPORT');
  const [status] = await runCodeNode('Build Failure Payload', [{ json: { statusCode: 503, statusMessage: 'Service Unavailable', data: '' } }]);
  assert.equal(status.json.stage, 'HTTP_STATUS');
  console.log(`Failure alert:\n${failure.json.text}\n`);

  const suppressed = await runCodeNode('Format Unhandled Error', [{ json: { execution: { lastNodeExecuted: 'Abort Execution' } } }]);
  assert.equal(suppressed.length, 0, 'Controlled aborts must not trigger a duplicate critical alert');
  const critical = await runCodeNode('Format Unhandled Error', [{
    json: { workflow: { name: workflow.name }, execution: { id: '42', lastNodeExecuted: 'Append Snapshot to History', error: { message: 'Quota exceeded' }, mode: 'trigger' } },
  }]);
  assert.equal(critical.length, 1);

  console.log('SIMULATION PASSED');
}

main().catch((error) => {
  console.error('SIMULATION FAILED:', error.message);
  process.exit(1);
});
