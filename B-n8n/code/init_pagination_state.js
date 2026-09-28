const config = $('Workflow Config').first().json;

const maxPages = Number(config.maxPages);
if (!Number.isInteger(maxPages) || maxPages < 1) {
  throw new Error(`Invalid maxPages in Workflow Config: ${config.maxPages}`);
}

return [
  {
    json: {
      page: 1,
      maxPages,
      pagesFetched: 0,
      runId: String($execution.id),
      runStartedAt: $now.toISO(),
      products: [],
    },
  },
];
