const result = $input.first().json;
const scrapedAt = $now.toISO();

const products = (result.products || []).map((product) => ({
  ...product,
  run_id: result.runId,
  scraped_at: scrapedAt,
}));

if (products.length === 0) {
  throw new Error(`Run ${result.runId} finished pagination with zero products; refusing to persist an empty snapshot.`);
}

return [
  {
    json: {
      runId: result.runId,
      runStartedAt: result.runStartedAt,
      scrapedAt,
      pagesFetched: result.pagesFetched,
      truncatedAtMaxPages: Boolean(result.hasNextPage) && result.page >= result.maxPages,
      productCount: products.length,
      products,
    },
  },
];
