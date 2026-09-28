const current = $input.first().json;

return [
  {
    json: {
      page: current.page + 1,
      maxPages: current.maxPages,
      pagesFetched: current.pagesFetched,
      runId: current.runId,
      runStartedAt: current.runStartedAt,
      products: current.products,
    },
  },
];
