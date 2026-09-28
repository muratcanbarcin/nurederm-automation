const input = $input.first().json;
const state = $('Pagination State').first().json;

let stage;
let detail;

if (input.error !== undefined) {
  stage = 'HTTP_TRANSPORT';
  detail = typeof input.error === 'string' ? input.error : input.error.message ?? JSON.stringify(input.error);
} else if (input.status === 'error') {
  stage = 'EXTRACTION';
  detail = input.reason;
} else {
  stage = 'HTTP_STATUS';
  detail = `Unexpected HTTP ${input.statusCode ?? 'n/a'} ${input.statusMessage ?? ''}`.trim();
}

const page = input.page ?? state.page ?? 'n/a';
const pagesFetched = input.pagesFetched ?? state.pagesFetched ?? 0;
const runId = input.runId ?? state.runId ?? String($execution.id);
const failedUrl = `https://webscraper.io/test-sites/e-commerce/static/computers/laptops?page=${page}`;

const escapeMarkdown = (value) => String(value ?? '').replace(/([_*`\[])/g, '\\$1');

const text = [
  '*Laptop Price Monitor - RUN ABORTED*',
  `Stage: \`${stage}\``,
  `Page: ${page} | Pages completed before failure: ${pagesFetched}`,
  `URL: ${failedUrl}`,
  `Detail: ${escapeMarkdown(detail)}`,
  `Run: \`${escapeMarkdown(runId)}\` | ${escapeMarkdown($now.toISO())}`,
  '_No snapshot was persisted for this run._',
].join('\n');

return [
  {
    json: {
      stage,
      detail,
      page,
      runId,
      failedUrl,
      text,
      summary: `Laptop price scrape aborted at stage ${stage} (page ${page}): ${detail}`,
    },
  },
];
