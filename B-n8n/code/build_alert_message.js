const MAX_LINES_PER_SECTION = 25;
const snapshot = $('Finalize Snapshot').first().json;
const changes = $input.all().map((item) => item.json);

const escapeMarkdown = (value) => String(value ?? '').replace(/([_*`\[])/g, '\\$1');
const money = (value) => `$${Number(value).toFixed(2)}`;
const signedPct = (value) => `${value > 0 ? '+' : ''}${Number(value).toFixed(2)}%`;

const describe = (row) => {
  const title = `[${escapeMarkdown(row.title)}](${row.url})`;
  if (row.change_type === 'NEW') {
    return `- ${title}: ${money(row.price)} (new listing)`;
  }
  return `- ${title}: ${money(row.previous_price)} -> *${money(row.price)}* (${signedPct(row.price_delta_pct)})`;
};

const section = (heading, rows) => {
  if (rows.length === 0) return [];
  const lines = rows.slice(0, MAX_LINES_PER_SECTION).map(describe);
  if (rows.length > MAX_LINES_PER_SECTION) {
    lines.push(`_...and ${rows.length - MAX_LINES_PER_SECTION} more_`);
  }
  return ['', `*${heading} (${rows.length})*`, ...lines];
};

const byMagnitude = (a, b) => Math.abs(b.price_delta_pct) - Math.abs(a.price_delta_pct);
const anomalies = changes.filter((r) => r.is_anomaly).sort(byMagnitude);
const priceDown = changes.filter((r) => r.change_type === 'PRICE_DOWN' && !r.is_anomaly).sort(byMagnitude);
const priceUp = changes.filter((r) => r.change_type === 'PRICE_UP' && !r.is_anomaly).sort(byMagnitude);
const newListings = changes.filter((r) => r.change_type === 'NEW');

const lines = [
  '*Laptop Price Monitor - Change Report*',
  `Run: \`${escapeMarkdown(snapshot.runId)}\` | ${escapeMarkdown(snapshot.scrapedAt)}`,
  `Scanned: ${snapshot.productCount} products across ${snapshot.pagesFetched} pages | Changes: ${changes.length}`,
  ...section('ANOMALY - price moved beyond threshold', anomalies),
  ...section('Price drops', priceDown),
  ...section('Price increases', priceUp),
  ...section('New listings', newListings),
];

if (snapshot.truncatedAtMaxPages) {
  lines.push('', '_Warning: pagination stopped at the maxPages safety bound; results may be incomplete._');
}

return [
  {
    json: {
      text: lines.join('\n').slice(0, 4000),
      changeCount: changes.length,
      anomalyCount: anomalies.length,
    },
  },
];
