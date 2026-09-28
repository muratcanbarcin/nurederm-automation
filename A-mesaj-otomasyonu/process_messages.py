"""Customer message triage for Nurederm.

Loads inbound customer messages, classifies each one into a support category,
enforces medical/legal handoff rules, verifies order ownership against the
DummyJSON carts API (IDOR protection), enriches product/price replies from the
DummyJSON product search API, assigns an operational priority and writes draft
replies to talepler.json and talepler.csv.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_DIR = Path(__file__).resolve().parent
INPUT_PATH = BASE_DIR / "mesajlar.json"
OUTPUT_PATH = BASE_DIR / "talepler.json"
CSV_PATH = BASE_DIR / "talepler.csv"
CSV_COLUMNS: tuple[str, ...] = (
    "id", "kanal", "musteri_id", "konu", "oncelik", "devret", "cevap_taslagi", "not",
)

CARTS_API_URL = "https://dummyjson.com/carts/{order_id}"
PRODUCT_SEARCH_API_URL = "https://dummyjson.com/products/search"
HTTP_TIMEOUT_SECONDS = 10

SECURITY_NOTE_PREFIX = "SECURITY:"

logger = logging.getLogger("process_messages")


class Category(str, Enum):
    PRODUCT_QUESTION = "urun-sorusu"
    PRICE = "fiyat"
    ORDER_STATUS = "siparis-durumu"
    RETURN_COMPLAINT = "iade-sikayet"
    ADVERSE_EFFECT = "istenmeyen-etki"
    OTHER = "diger"


HANDOFF_CATEGORIES: frozenset[Category] = frozenset(
    {Category.RETURN_COMPLAINT, Category.ADVERSE_EFFECT}
)


class Priority(str, Enum):
    HIGH = "YUKSEK"
    MEDIUM = "ORTA"
    LOW = "DUSUK"


PRIORITY_RANK: dict[Priority, int] = {Priority.LOW: 0, Priority.MEDIUM: 1, Priority.HIGH: 2}

# Category baseline; order-status outcomes (IDOR mismatch, unverified order) can escalate it.
CATEGORY_PRIORITY: dict[Category, Priority] = {
    Category.ADVERSE_EFFECT: Priority.HIGH,
    Category.RETURN_COMPLAINT: Priority.MEDIUM,
    Category.ORDER_STATUS: Priority.LOW,
    Category.PRICE: Priority.LOW,
    Category.PRODUCT_QUESTION: Priority.LOW,
    Category.OTHER: Priority.LOW,
}


def resolve_priority(category: Category, outcome: Priority) -> Priority:
    """Return the higher of the category baseline and the draft outcome priority."""
    baseline = CATEGORY_PRIORITY[category]
    return outcome if PRIORITY_RANK[outcome] > PRIORITY_RANK[baseline] else baseline


class InboundMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    kanal: str
    musteri_id: int
    mesaj: str


class TicketResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    konu: Category
    oncelik: Priority
    devret: bool
    cevap_taslagi: str
    note: str = Field(alias="not")


# ---------------------------------------------------------------------------
# Text normalization & language detection
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Lowercase with Turkish-aware handling of dotted/dotless I."""
    return text.replace("I", "ı").replace("İ", "i").lower()


ENGLISH_MARKERS = re.compile(
    r"\b(hi|hello|where|my|order|is|the|please|thanks|when|what|it|has|been)\b"
)


def detect_language(text: str) -> str:
    """Return 'en' when the message is predominantly English, otherwise 'tr'."""
    words = re.findall(r"[a-zçğıöşü]+", normalize(text))
    if not words:
        return "tr"
    english_hits = sum(1 for word in words if ENGLISH_MARKERS.fullmatch(word))
    return "en" if english_hits / len(words) >= 0.3 else "tr"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

ORDER_ID_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(\d+)\s*(?:numaralı|nolu|no'?lu)\s*sipariş"),
    re.compile(r"sipariş(?:im|imin)?\s*(?:no|numarası|numaram)\s*[:#]?\s*(\d+)"),
    re.compile(r"order\s*(?:no\.?|number)?\s*#?\s*(\d+)"),
    re.compile(r"#\s*(\d+)"),
)

ADVERSE_EFFECT_KEYWORDS = (
    "yandı", "yanma", "kızar", "kaşın", "alerji", "sivilce", "döküntü",
    "şişl", "şişti", "tahriş", "leke yaptı", "reaksiyon", "burn", "rash",
    "itch", "allerg", "irritat",
)
RETURN_COMPLAINT_KEYWORDS = (
    "iade", "ezik", "kırık", "hasarlı", "bozuk", "şikayet", "şikâyet",
    "yanlış ürün", "eksik geldi", "para iadesi", "refund", "return", "damaged",
    "broken", "complaint",
)
ORDER_STATUS_KEYWORDS = (
    "siparişim", "siparişimin", "kargom", "kargoya verilir", "elime ulaş",
    "ne zaman gelir", "where is my order", "my order", "tracking",
)
PRICE_KEYWORDS = (
    "fiyat", "ne kadar", "kaç tl", "kaç lira", "ücret", "indirim", "kampanya",
    "kupon", "price", "cost", "discount",
)
PRODUCT_KEYWORDS = (
    "serum", "krem", "tonik", "içerik", "cilt tipi", "cilt tipine", "ciltte",
    "ürünleriniz", "ürününüz", " ml ", "alkol", "paraben", "vegan",
    "hayvanlar üzerinde test", "kullanılır mı", "uygun mu", "uygundur",
    "ingredient", "skin type",
)
SPAM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:https?://|www\.|bit\.ly/|t\.co/)\S+"),
    re.compile(r"takipçi\s*(?:kas|sat|artır)"),
    re.compile(r"%\s*100\s*organik"),
)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def extract_order_id(text: str) -> int | None:
    normalized = normalize(text)
    for pattern in ORDER_ID_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return int(match.group(1))
    return None


def is_spam(text: str) -> bool:
    normalized = normalize(text)
    return any(pattern.search(normalized) for pattern in SPAM_PATTERNS)


def detect_intents(text: str) -> list[Category]:
    """Return all matching intents ordered by business priority (highest first)."""
    normalized = normalize(text)
    intents: list[Category] = []

    if _contains_any(normalized, ADVERSE_EFFECT_KEYWORDS):
        intents.append(Category.ADVERSE_EFFECT)
    if _contains_any(normalized, RETURN_COMPLAINT_KEYWORDS):
        intents.append(Category.RETURN_COMPLAINT)
    if extract_order_id(text) is not None or _contains_any(normalized, ORDER_STATUS_KEYWORDS):
        intents.append(Category.ORDER_STATUS)
    if _contains_any(normalized, PRICE_KEYWORDS):
        intents.append(Category.PRICE)
    if _contains_any(normalized, PRODUCT_KEYWORDS):
        intents.append(Category.PRODUCT_QUESTION)

    return intents


def classify(text: str) -> Category:
    if is_spam(text):
        return Category.OTHER
    intents = detect_intents(text)
    return intents[0] if intents else Category.OTHER


# ---------------------------------------------------------------------------
# Order lookup (DummyJSON)
# ---------------------------------------------------------------------------

class LookupStatus(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    ERROR = "error"


@dataclass(frozen=True)
class CartLookup:
    status: LookupStatus
    cart: dict[str, Any] | None = None
    error: str | None = None


CartFetcher = Callable[[int], CartLookup]


def build_http_session() -> requests.Session:
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"Accept": "application/json"})
    return session


def make_cart_fetcher(session: requests.Session) -> CartFetcher:
    def fetch_cart(order_id: int) -> CartLookup:
        url = CARTS_API_URL.format(order_id=order_id)
        try:
            response = session.get(url, timeout=HTTP_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            logger.warning("Cart lookup failed for order %s: %s", order_id, exc)
            return CartLookup(LookupStatus.ERROR, error=str(exc))

        if response.status_code == 404:
            return CartLookup(LookupStatus.NOT_FOUND)
        if not response.ok:
            return CartLookup(LookupStatus.ERROR, error=f"HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            return CartLookup(LookupStatus.ERROR, error=f"Invalid JSON: {exc}")
        if not isinstance(payload, dict) or "userId" not in payload:
            return CartLookup(LookupStatus.ERROR, error="Unexpected cart payload shape")
        return CartLookup(LookupStatus.FOUND, cart=payload)

    return fetch_cart


# ---------------------------------------------------------------------------
# Product search (DummyJSON)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProductTerm:
    trigger: str
    search_terms: tuple[str, ...]
    specific: bool


# Ordered longest/most specific first; matched triggers are consumed so that
# "güneş kremi" does not additionally yield the generic "krem" term.
PRODUCT_TERMS: tuple[ProductTerm, ...] = (
    ProductTerm("güneş kremi", ("sunscreen", "sun cream"), True),
    ProductTerm("sunscreen", ("sunscreen",), True),
    ProductTerm("c vitamini", ("vitamin c",), True),
    ProductTerm("vitamin c", ("vitamin c",), True),
    ProductTerm("retinol", ("retinol",), True),
    ProductTerm("nemlendirici", ("moisturizer", "moisture"), True),
    ProductTerm("moisturi", ("moisturizer", "moisture"), True),
    ProductTerm("serum", ("serum",), False),
    ProductTerm("tonik", ("toner",), False),
    ProductTerm("toner", ("toner",), False),
    ProductTerm("losyon", ("lotion",), False),
    ProductTerm("lotion", ("lotion",), False),
    ProductTerm("krem", ("cream",), False),
    ProductTerm("cream", ("cream",), False),
)

# DummyJSON search is a loose substring match across all categories
# (e.g. "cream" returns "Ice Cream"), so only cosmetic categories are accepted.
COSMETIC_CATEGORIES: frozenset[str] = frozenset({"beauty", "skin-care"})


def extract_product_terms(text: str) -> list[str]:
    """Return English search terms for cosmetic keywords found in the message.

    When a specific term (e.g. retinol) is present, generic terms (e.g. serum)
    are dropped: answering a retinol question with an unrelated serum would be
    misleading.
    """
    remaining = normalize(text)
    specific: list[str] = []
    generic: list[str] = []
    for term in PRODUCT_TERMS:
        if term.trigger not in remaining:
            continue
        remaining = remaining.replace(term.trigger, " ")
        bucket = specific if term.specific else generic
        bucket.extend(t for t in term.search_terms if t not in bucket)
    return specific or generic


@dataclass(frozen=True)
class ProductSearchResult:
    status: LookupStatus
    products: tuple[dict[str, Any], ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class ProductMatch:
    term: str
    product_id: int
    title: str
    price: float


@dataclass(frozen=True)
class ProductEnrichment:
    terms: tuple[str, ...]
    match: ProductMatch | None = None
    errors: tuple[str, ...] = ()


ProductSearcher = Callable[[str], ProductSearchResult]


def make_product_searcher(session: requests.Session) -> ProductSearcher:
    cache: dict[str, ProductSearchResult] = {}

    def search_products(term: str) -> ProductSearchResult:
        if term in cache:
            return cache[term]
        try:
            response = session.get(
                PRODUCT_SEARCH_API_URL, params={"q": term}, timeout=HTTP_TIMEOUT_SECONDS
            )
        except requests.RequestException as exc:
            logger.warning("Product search failed for %r: %s", term, exc)
            return ProductSearchResult(LookupStatus.ERROR, error=str(exc))

        if not response.ok:
            return ProductSearchResult(LookupStatus.ERROR, error=f"HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            return ProductSearchResult(LookupStatus.ERROR, error=f"Invalid JSON: {exc}")
        products = payload.get("products") if isinstance(payload, dict) else None
        if not isinstance(products, list):
            return ProductSearchResult(LookupStatus.ERROR, error="Unexpected search payload shape")

        result = ProductSearchResult(
            LookupStatus.FOUND if products else LookupStatus.NOT_FOUND,
            tuple(p for p in products if isinstance(p, dict)),
        )
        cache[term] = result
        return result

    return search_products


def select_relevant_product(term: str, products: tuple[dict[str, Any], ...]) -> ProductMatch | None:
    """Pick the best cosmetic product whose title (preferred) or description contains the term."""
    pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
    best: tuple[int, ProductMatch] | None = None
    for product in products:
        if product.get("category") not in COSMETIC_CATEGORIES:
            continue
        title = product.get("title")
        price = product.get("price")
        if not isinstance(title, str) or not title.strip() or not isinstance(price, (int, float)):
            continue
        if pattern.search(title):
            score = 2
        elif pattern.search(str(product.get("description", ""))):
            score = 1
        else:
            continue
        if best is None or score > best[0]:
            best = (score, ProductMatch(term, int(product.get("id", 0)), title.strip(), float(price)))
    return best[1] if best else None


def enrich_from_catalog(text: str, search_products: ProductSearcher | None) -> ProductEnrichment:
    terms = tuple(extract_product_terms(text))
    if not terms or search_products is None:
        return ProductEnrichment(terms)
    errors: list[str] = []
    for term in terms:
        result = search_products(term)
        if result.status is LookupStatus.ERROR:
            errors.append(f"{term}: {result.error}")
            continue
        match = select_relevant_product(term, result.products)
        if match is not None:
            return ProductEnrichment(terms, match, tuple(errors))
    return ProductEnrichment(terms, None, tuple(errors))


def _enrichment_note(enrichment: ProductEnrichment) -> str:
    if enrichment.match is not None:
        match = enrichment.match
        return (
            f"Product search '{match.term}' matched '{match.title}' (id {match.product_id}, "
            f"{_format_money(match.price)}); verify against the official catalog before sending."
        )
    if not enrichment.terms:
        return "No product keyword detected; catalog search skipped."
    searched = ", ".join(f"'{term}'" for term in enrichment.terms)
    if enrichment.errors:
        return f"Product search unavailable ({'; '.join(enrichment.errors)}); generic reply used."
    return f"Product search for {searched} returned no relevant cosmetic match; generic reply used."


# ---------------------------------------------------------------------------
# Reply drafting
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Draft:
    devret: bool
    reply: str
    note: str
    covered_intents: frozenset[Category] = frozenset()
    priority: Priority = Priority.LOW


def _format_money(amount: float) -> str:
    return f"${amount:,.2f}"


def _cart_summary(cart: dict[str, Any], lang: str) -> str:
    lines = [
        f"- {product['title']} x{product['quantity']}"
        for product in cart.get("products", [])
    ]
    total = float(cart.get("total", 0))
    discounted = float(cart.get("discountedTotal", total))
    if lang == "en":
        total_line = f"Total: {_format_money(total)}"
        if discounted < total:
            total_line += f" (after discount: {_format_money(discounted)})"
    else:
        total_line = f"Toplam tutar: {_format_money(total)}"
        if discounted < total:
            total_line += f" (indirimli: {_format_money(discounted)})"
    return "\n".join([*lines, total_line])


def draft_order_status(
    message: InboundMessage, lang: str, fetch_cart: CartFetcher
) -> Draft:
    order_id = extract_order_id(message.mesaj)
    if order_id is None:
        reply = (
            "Could you please share your order number so we can check its status?"
            if lang == "en"
            else "Merhaba, siparişinizi kontrol edebilmemiz için sipariş numaranızı "
            "paylaşabilir misiniz?"
        )
        return Draft(False, reply, "Order status requested without an order number.")

    lookup = fetch_cart(order_id)

    if lookup.status is LookupStatus.NOT_FOUND:
        reply = (
            f"We couldn't find an order with number {order_id}. Could you please "
            "double-check the number? We'll be happy to help."
            if lang == "en"
            else f"Merhaba, {order_id} numaralı bir siparişe ulaşamadık. Sipariş "
            "numaranızı kontrol edip tekrar paylaşabilir misiniz? Yardımcı olmaktan "
            "memnuniyet duyarız."
        )
        return Draft(
            False, reply, f"Order {order_id} not found (HTTP 404).", priority=Priority.MEDIUM
        )

    if lookup.status is LookupStatus.ERROR or lookup.cart is None:
        reply = (
            "Thank you for your message. Our team will check your order and get back "
            "to you shortly."
            if lang == "en"
            else "Merhaba, mesajınız için teşekkürler. Ekibimiz siparişinizi kontrol "
            "edip en kısa sürede size dönüş yapacak."
        )
        return Draft(
            True,
            reply,
            f"Order lookup for {order_id} failed ({lookup.error}); manual check required.",
            priority=Priority.MEDIUM,
        )

    cart_owner = lookup.cart.get("userId")
    if cart_owner != message.musteri_id:
        reply = (
            "For your security, we could not verify the order number you shared "
            "against your account, so we cannot share order details over this "
            "channel. A member of our team will contact you to verify your identity."
            if lang == "en"
            else "Merhaba, güvenliğiniz için paylaştığınız sipariş numarasını "
            "hesabınızla doğrulayamadık; bu nedenle sipariş detaylarını bu kanaldan "
            "paylaşamıyoruz. Ekibimiz kimlik doğrulaması için sizinle iletişime "
            "geçecektir."
        )
        note = (
            f"{SECURITY_NOTE_PREFIX} Potential IDOR / customer mismatch. Customer "
            f"{message.musteri_id} requested order {order_id}, which belongs to user "
            f"{cart_owner}. Order contents concealed; identity verification required."
        )
        return Draft(True, reply, note, priority=Priority.HIGH)

    summary = _cart_summary(lookup.cart, lang)
    reply = (
        f"Hello! Here are the details of your order #{order_id}:\n{summary}\n"
        "Our team will share the shipping update with you shortly."
        if lang == "en"
        else f"Merhaba, {order_id} numaralı siparişinizin detayları:\n{summary}\n"
        "Kargo bilgisi ekibimiz tarafından en kısa sürede paylaşılacaktır."
    )
    return Draft(False, reply, f"Order {order_id} ownership verified for customer {message.musteri_id}.")


def draft_adverse_effect(lang: str) -> Draft:
    reply = (
        "We are very sorry to hear about your experience. Your message has been "
        "forwarded to our specialist team, who will contact you as soon as possible."
        if lang == "en"
        else "Merhaba, yaşadığınız durum için çok üzgünüz. Mesajınızı uzman ekibimize "
        "ilettik; en kısa sürede sizinle iletişime geçecekler. Geçmiş olsun."
    )
    note = (
        "Possible adverse reaction reported. Mandatory human handoff; no medical "
        "advice or product recommendation given."
    )
    return Draft(True, reply, note)


def draft_return_complaint(lang: str) -> Draft:
    reply = (
        "We are sorry for the inconvenience. Your request has been forwarded to our "
        "customer care team, who will contact you shortly about the next steps."
        if lang == "en"
        else "Merhaba, yaşadığınız olumsuzluk için özür dileriz. Talebiniz müşteri "
        "hizmetleri ekibimize iletildi; süreçle ilgili en kısa sürede sizinle "
        "iletişime geçecekler."
    )
    return Draft(True, reply, "Return/complaint request. Mandatory human handoff.")


def draft_price(lang: str, enrichment: ProductEnrichment) -> Draft:
    match = enrichment.match
    if match is not None:
        price = _format_money(match.price)
        reply = (
            f'Thank you for your interest! The product matching your request, "{match.title}", '
            f"is currently listed at {price}. Active campaigns are available on our website; "
            "our team will be happy to share further details."
            if lang == "en"
            else f'Merhaba, ilginiz için teşekkürler! Sorduğunuz ürünle eşleşen "{match.title}" '
            f"ürünümüzün güncel fiyatı {price}. Aktif kampanyalarımızı web sitemizde "
            "bulabilirsiniz; dilerseniz ekibimiz detayları size ayrıca iletecektir."
        )
    else:
        reply = (
            "Thank you for your interest! Current prices and active campaigns are listed "
            "on our website; our team will also share the details with you shortly."
            if lang == "en"
            else "Merhaba, ilginiz için teşekkürler! Güncel fiyatlarımızı ve aktif "
            "kampanyalarımızı web sitemizde bulabilirsiniz; ekibimiz detayları kısa "
            "süre içinde size ayrıca iletecektir."
        )
    return Draft(
        False,
        reply,
        f"Price inquiry. Verify current price list before sending. {_enrichment_note(enrichment)}",
        frozenset({Category.PRODUCT_QUESTION}) if match is not None else frozenset(),
    )


def draft_product_question(lang: str, enrichment: ProductEnrichment) -> Draft:
    match = enrichment.match
    if match is not None:
        price = _format_money(match.price)
        reply = (
            f'Thank you for your question! Our catalog includes "{match.title}" '
            f"(current price: {price}), which matches your request. Our team will share "
            "its ingredient and usage details from the official product information shortly."
            if lang == "en"
            else f'Merhaba, sorunuz için teşekkürler! Kataloğumuzda sorunuzla eşleşen '
            f'"{match.title}" ürünümüz bulunuyor (güncel fiyatı: {price}). Ürünün içerik '
            "ve kullanım bilgilerini ekibimiz resmî ürün bilgi formuna göre kısa süre "
            "içinde size iletecektir."
        )
    else:
        reply = (
            "Thank you for your question! Detailed product information is available on "
            "our product pages; our team will share the specifics with you shortly."
            if lang == "en"
            else "Merhaba, sorunuz için teşekkürler! Ürünlerimizle ilgili detaylı bilgiyi "
            "ürün sayfalarımızda bulabilirsiniz; ekibimiz sorunuzla ilgili bilgiyi kısa "
            "süre içinde size iletecektir."
        )
    return Draft(
        False,
        reply,
        "Product question. Answer from official product data sheet only; no skin "
        f"diagnosis or personal recommendation. {_enrichment_note(enrichment)}",
        frozenset({Category.PRICE}) if match is not None else frozenset(),
    )


def draft_spam() -> Draft:
    return Draft(
        False,
        "Yanıt gönderilmemelidir.",
        "Spam / suspicious link detected. Do not reply or open links; consider blocking the sender.",
    )


def draft_other(lang: str) -> Draft:
    reply = (
        "Thank you for reaching out! Our team will get back to you shortly."
        if lang == "en"
        else "Merhaba, bize ulaştığınız için teşekkürler! Ekibimiz sorunuzu "
        "yanıtlamak için en kısa sürede size dönüş yapacak."
    )
    return Draft(False, reply, "General inquiry. Answer with standard company information.")


SECONDARY_INTENT_REPLIES: dict[Category, dict[str, str]] = {
    Category.PRICE: {
        "tr": "Fiyat sorunuzla ilgili güncel bilgiyi ekibimiz ayrıca paylaşacaktır.",
        "en": "Our team will also share the current pricing you asked about.",
    },
    Category.PRODUCT_QUESTION: {
        "tr": "Ürün sorunuzla ilgili bilgiyi ekibimiz ayrıca paylaşacaktır.",
        "en": "Our team will also answer your product question.",
    },
}


def _append_secondary_intents(
    draft: Draft, category: Category, text: str, lang: str
) -> Draft:
    if category in HANDOFF_CATEGORIES:
        return draft
    secondary = next(
        (
            intent
            for intent in detect_intents(text)
            if intent is not category and intent in SECONDARY_INTENT_REPLIES
        ),
        None,
    )
    if secondary is None:
        return draft
    reply = (
        draft.reply
        if draft.note.startswith(SECURITY_NOTE_PREFIX) or secondary in draft.covered_intents
        else f"{draft.reply}\n{SECONDARY_INTENT_REPLIES[secondary][lang]}"
    )
    return replace(draft, reply=reply, note=f"{draft.note} Secondary intent: {secondary.value}.")


def process_message(
    message: InboundMessage,
    fetch_cart: CartFetcher,
    search_products: ProductSearcher | None = None,
) -> TicketResult:
    lang = detect_language(message.mesaj)
    category = classify(message.mesaj)

    if category is Category.ADVERSE_EFFECT:
        draft = draft_adverse_effect(lang)
    elif category is Category.RETURN_COMPLAINT:
        draft = draft_return_complaint(lang)
    elif category is Category.ORDER_STATUS:
        draft = draft_order_status(message, lang, fetch_cart)
    elif category is Category.PRICE:
        draft = draft_price(lang, enrich_from_catalog(message.mesaj, search_products))
    elif category is Category.PRODUCT_QUESTION:
        draft = draft_product_question(lang, enrich_from_catalog(message.mesaj, search_products))
    elif is_spam(message.mesaj):
        draft = draft_spam()
    else:
        draft = draft_other(lang)

    draft = _append_secondary_intents(draft, category, message.mesaj, lang)

    devret = True if category in HANDOFF_CATEGORIES else draft.devret
    return TicketResult(
        id=message.id,
        konu=category,
        oncelik=resolve_priority(category, draft.priority),
        devret=devret,
        cevap_taslagi=draft.reply,
        note=draft.note,
    )


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_messages(path: Path) -> list[InboundMessage]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path.name} must contain a JSON array")
    return [InboundMessage.model_validate(item) for item in raw]


def write_results(path: Path, results: list[TicketResult]) -> None:
    payload = [result.model_dump(mode="json", by_alias=True) for result in results]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export_csv(
    path: Path, results: list[TicketResult], messages: list[InboundMessage]
) -> None:
    """Write tickets joined with their source channel/customer as UTF-8 BOM CSV for Excel."""
    messages_by_id = {message.id: message for message in messages}
    missing = [result.id for result in results if result.id not in messages_by_id]
    if missing:
        raise ValueError(f"Tickets without a source message: {missing}")

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(CSV_COLUMNS)
        for result in results:
            message = messages_by_id[result.id]
            writer.writerow(
                (
                    result.id,
                    message.kanal,
                    message.musteri_id,
                    result.konu.value,
                    result.oncelik.value,
                    "true" if result.devret else "false",
                    result.cevap_taslagi,
                    result.note,
                )
            )


def run(
    input_path: Path = INPUT_PATH,
    output_path: Path = OUTPUT_PATH,
    fetch_cart: CartFetcher | None = None,
    search_products: ProductSearcher | None = None,
    csv_path: Path | None = CSV_PATH,
) -> list[TicketResult]:
    messages = load_messages(input_path)
    logger.info("Loaded %d messages from %s", len(messages), input_path.name)

    if fetch_cart is None or search_products is None:
        session = build_http_session()
        fetch_cart = fetch_cart or make_cart_fetcher(session)
        search_products = search_products or make_product_searcher(session)

    results = [process_message(message, fetch_cart, search_products) for message in messages]
    write_results(output_path, results)
    logger.info("Wrote %d tickets to %s", len(results), output_path.name)
    if csv_path is not None:
        export_csv(csv_path, results, messages)
        logger.info("Exported %d tickets to %s", len(results), csv_path.name)
    return results


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        results = run()
    except (OSError, ValueError, ValidationError) as exc:
        logger.error("Processing failed: %s", exc)
        return 1

    for result in results:
        logger.info(
            "id=%-2d konu=%-15s oncelik=%-6s devret=%-5s %s",
            result.id,
            result.konu.value,
            result.oncelik.value,
            result.devret,
            "[SECURITY]" if result.note.startswith(SECURITY_NOTE_PREFIX) else "",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
