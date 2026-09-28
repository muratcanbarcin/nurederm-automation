"""Customer message triage for Nurederm.

Loads inbound customer messages, classifies each one into a support category,
enforces medical/legal handoff rules, verifies order ownership against the
DummyJSON carts API (IDOR protection) and writes draft replies to talepler.json.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
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

CARTS_API_URL = "https://dummyjson.com/carts/{order_id}"
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
# Reply drafting
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Draft:
    devret: bool
    reply: str
    note: str


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
        return Draft(False, reply, f"Order {order_id} not found (HTTP 404).")

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
        return Draft(True, reply, note)

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


def draft_price(lang: str) -> Draft:
    reply = (
        "Thank you for your interest! Current prices and active campaigns are listed "
        "on our website; our team will also share the details with you shortly."
        if lang == "en"
        else "Merhaba, ilginiz için teşekkürler! Güncel fiyatlarımızı ve aktif "
        "kampanyalarımızı web sitemizde bulabilirsiniz; ekibimiz detayları kısa "
        "süre içinde size ayrıca iletecektir."
    )
    return Draft(False, reply, "Price inquiry. Verify current price list before sending.")


def draft_product_question(lang: str) -> Draft:
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
        "diagnosis or personal recommendation.",
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
        if draft.note.startswith(SECURITY_NOTE_PREFIX)
        else f"{draft.reply}\n{SECONDARY_INTENT_REPLIES[secondary][lang]}"
    )
    return Draft(draft.devret, reply, f"{draft.note} Secondary intent: {secondary.value}.")


def process_message(message: InboundMessage, fetch_cart: CartFetcher) -> TicketResult:
    lang = detect_language(message.mesaj)
    category = classify(message.mesaj)

    if category is Category.ADVERSE_EFFECT:
        draft = draft_adverse_effect(lang)
    elif category is Category.RETURN_COMPLAINT:
        draft = draft_return_complaint(lang)
    elif category is Category.ORDER_STATUS:
        draft = draft_order_status(message, lang, fetch_cart)
    elif category is Category.PRICE:
        draft = draft_price(lang)
    elif category is Category.PRODUCT_QUESTION:
        draft = draft_product_question(lang)
    elif is_spam(message.mesaj):
        draft = draft_spam()
    else:
        draft = draft_other(lang)

    draft = _append_secondary_intents(draft, category, message.mesaj, lang)

    devret = True if category in HANDOFF_CATEGORIES else draft.devret
    return TicketResult(
        id=message.id,
        konu=category,
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


def run(
    input_path: Path = INPUT_PATH,
    output_path: Path = OUTPUT_PATH,
    fetch_cart: CartFetcher | None = None,
) -> list[TicketResult]:
    messages = load_messages(input_path)
    logger.info("Loaded %d messages from %s", len(messages), input_path.name)

    if fetch_cart is None:
        fetch_cart = make_cart_fetcher(build_http_session())

    results = [process_message(message, fetch_cart) for message in messages]
    write_results(output_path, results)
    logger.info("Wrote %d tickets to %s", len(results), output_path.name)
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
            "id=%-2d konu=%-15s devret=%-5s %s",
            result.id,
            result.konu.value,
            result.devret,
            "[SECURITY]" if result.note.startswith(SECURITY_NOTE_PREFIX) else "",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
