const snapshot = $('Finalize Snapshot').first().json;
const config = $('Workflow Config').first().json;
const anomalyThresholdPct = Number(config.priceAnomalyThresholdPct ?? 20);

const round2 = (value) => Math.round(value * 100) / 100;

const toNumber = (value) => {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const parsed = parseFloat(String(value ?? '').replace(/[^0-9.-]/g, ''));
  return Number.isFinite(parsed) ? parsed : null;
};

const latestById = new Map();
for (const item of $input.all()) {
  const row = item.json || {};
  const productId = String(row.product_id ?? '').trim();
  const price = toNumber(row.price);
  if (!productId || price === null) continue;

  const timestamp = Date.parse(row.scraped_at) || 0;
  const previous = latestById.get(productId);
  if (!previous || timestamp >= previous.timestamp) {
    latestById.set(productId, { price, timestamp });
  }
}

const isBaselineRun = latestById.size === 0;

return snapshot.products.map((product) => {
  const previous = latestById.get(String(product.product_id));

  let changeType = 'UNCHANGED';
  let previousPrice = null;
  let priceDelta = 0;
  let priceDeltaPct = 0;

  if (!previous) {
    changeType = 'NEW';
  } else {
    previousPrice = previous.price;
    priceDelta = round2(product.price - previous.price);
    if (Math.abs(priceDelta) >= 0.01) {
      changeType = priceDelta > 0 ? 'PRICE_UP' : 'PRICE_DOWN';
      priceDeltaPct = previous.price > 0 ? round2((priceDelta / previous.price) * 100) : 0;
    } else {
      priceDelta = 0;
    }
  }

  const isAnomaly = changeType.startsWith('PRICE_') && Math.abs(priceDeltaPct) >= anomalyThresholdPct;

  return {
    json: {
      run_id: product.run_id,
      scraped_at: product.scraped_at,
      product_id: product.product_id,
      title: product.title,
      price: product.price,
      currency: product.currency,
      review_count: product.review_count,
      rating: product.rating,
      url: product.url,
      page: product.page,
      change_type: changeType,
      previous_price: previousPrice,
      price_delta: priceDelta,
      price_delta_pct: priceDeltaPct,
      is_anomaly: isAnomaly,
      is_baseline_run: isBaselineRun,
    },
  };
});
