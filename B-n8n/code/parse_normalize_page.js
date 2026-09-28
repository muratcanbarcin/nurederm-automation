const BASE_ORIGIN = 'https://webscraper.io';

const state = $('Pagination State').first().json;
const response = $input.first().json;
const html = String(response.data ?? response.body ?? '');
const page = Number(state.page);

const decodeEntities = (value) =>
  String(value)
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim();

const sanitizePrice = (raw) => {
  const cleaned = String(raw ?? '')
    .replace(/[^0-9.,-]/g, '')
    .replace(/,/g, '');
  const value = parseFloat(cleaned);
  return Number.isFinite(value) ? Math.round(value * 100) / 100 : null;
};

const toAbsoluteUrl = (href) => {
  if (/^https?:\/\//i.test(href)) return href;
  return `${BASE_ORIGIN}${href.startsWith('/') ? '' : '/'}${href}`;
};

const readAttribute = (tag, attribute) => {
  const match = tag.match(new RegExp(`\\b${attribute}="([^"]*)"`, 'i'));
  return match ? decodeEntities(match[1]) : null;
};

const blocks = html.split(/class="[^"]*\bthumbnail\b[^"]*"/i).slice(1);

const pageProducts = [];
const invalidRows = [];

for (const block of blocks) {
  const anchorTag = (block.match(/<a\b[^>]*\bclass="[^"]*\btitle\b[^"]*"[^>]*>/i) || [])[0];
  const anchorText = (block.match(/<a\b[^>]*\bclass="[^"]*\btitle\b[^"]*"[^>]*>([\s\S]*?)<\/a>/i) || [])[1];
  const href = anchorTag ? readAttribute(anchorTag, 'href') : null;
  const title = (anchorTag && readAttribute(anchorTag, 'title')) || (anchorText ? decodeEntities(anchorText) : null);

  const rawPrice =
    (block.match(/itemprop="price"[^>]*>([^<]+)</i) || [])[1] ??
    (block.match(/class="[^"]*\bprice\b[^"]*"[^>]*>\s*(?:<[^>]+>\s*)*([^<]+)/i) || [])[1];
  const price = sanitizePrice(rawPrice);

  const rawReviews =
    (block.match(/itemprop="reviewCount"[^>]*>\s*(\d+)/i) || [])[1] ??
    (block.match(/(\d+)\s+reviews?/i) || [])[1];
  const reviewCount = rawReviews !== undefined ? parseInt(rawReviews, 10) : 0;

  const rating = parseInt((block.match(/data-rating="(\d+)"/i) || [])[1] ?? '0', 10);
  const descriptionRaw = (block.match(/class="[^"]*\bdescription\b[^"]*"[^>]*>([\s\S]*?)<\/p>/i) || [])[1];

  if (!href || !title || price === null) {
    invalidRows.push({ href, title, rawPrice: rawPrice ?? null });
    continue;
  }

  const url = toAbsoluteUrl(href);
  const productId = (url.match(/\/product\/(\d+)/) || [])[1] ?? url;

  pageProducts.push({
    product_id: String(productId),
    title,
    description: descriptionRaw ? decodeEntities(descriptionRaw) : '',
    price,
    currency: 'USD',
    review_count: reviewCount,
    rating,
    url,
    page,
  });
}

const hasNextPage = /rel="next"/i.test(html);
const pageNumbers = [...html.matchAll(/[?&]page=(\d+)/g)].map((m) => parseInt(m[1], 10));
const totalPagesDetected = pageNumbers.length ? Math.max(page, ...pageNumbers) : page;

const merged = new Map((state.products || []).map((p) => [p.product_id, p]));
for (const product of pageProducts) {
  if (!merged.has(product.product_id)) merged.set(product.product_id, product);
}

let status = 'ok';
let reason = null;
if (pageProducts.length === 0) {
  status = 'error';
  reason = `ZERO_PRODUCTS: page ${page} returned no parsable laptops (HTTP ${response.statusCode ?? 'n/a'}, ${html.length} bytes)`;
} else if (invalidRows.length > 0) {
  status = 'error';
  reason = `PARSE_FAILURE: ${invalidRows.length} product card(s) on page ${page} missing title/link/price`;
}

return [
  {
    json: {
      status,
      reason,
      page,
      maxPages: state.maxPages,
      pagesFetched: Number(state.pagesFetched || 0) + 1,
      hasNextPage,
      totalPagesDetected,
      pageProductCount: pageProducts.length,
      invalidRows,
      statusCode: response.statusCode ?? null,
      runId: state.runId,
      runStartedAt: state.runStartedAt,
      products: [...merged.values()],
    },
  },
];
