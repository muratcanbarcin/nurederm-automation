"""Render a standalone Turkish HTML dashboard (ozet.html) from mesajlar.json and talepler.json."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from string import Template
from typing import Any

from process_messages import (
    CSV_COLUMNS,
    HANDOFF_CATEGORIES,
    INPUT_PATH,
    OUTPUT_PATH,
    SECURITY_NOTE_PREFIX,
    Category,
    Priority,
)

HTML_PATH = OUTPUT_PATH.parent / "ozet.html"

CATEGORY_ORDER: tuple[Category, ...] = (
    Category.ORDER_STATUS,
    Category.PRODUCT_QUESTION,
    Category.PRICE,
    Category.OTHER,
    Category.RETURN_COMPLAINT,
    Category.ADVERSE_EFFECT,
)

CATEGORY_LABELS: dict[Category, str] = {
    Category.ORDER_STATUS: "Sipariş Durumu",
    Category.PRODUCT_QUESTION: "Ürün Sorusu",
    Category.PRICE: "Fiyat",
    Category.OTHER: "Diğer",
    Category.RETURN_COMPLAINT: "İade / Şikâyet",
    Category.ADVERSE_EFFECT: "İstenmeyen Etki",
}

CATEGORY_STYLES: dict[Category, str] = {
    Category.ORDER_STATUS: "bg-sky-50 text-sky-700 ring-sky-600/20",
    Category.PRODUCT_QUESTION: "bg-violet-50 text-violet-700 ring-violet-600/20",
    Category.PRICE: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    Category.OTHER: "bg-slate-100 text-slate-700 ring-slate-500/20",
    Category.RETURN_COMPLAINT: "bg-amber-50 text-amber-800 ring-amber-600/30",
    Category.ADVERSE_EFFECT: "bg-rose-50 text-rose-700 ring-rose-600/30",
}

PRIORITY_LABELS: dict[Priority, str] = {
    Priority.HIGH: "YÜKSEK",
    Priority.MEDIUM: "ORTA",
    Priority.LOW: "DÜŞÜK",
}

PRIORITY_STYLES: dict[Priority, tuple[str, str]] = {
    Priority.HIGH: ("bg-rose-50 text-rose-700 ring-rose-600/30", "bg-rose-500"),
    Priority.MEDIUM: ("bg-amber-50 text-amber-800 ring-amber-600/30", "bg-amber-500"),
    Priority.LOW: ("bg-emerald-50 text-emerald-700 ring-emerald-600/20", "bg-emerald-500"),
}

CHANNEL_META: dict[str, tuple[str, str]] = {
    "whatsapp": ("WhatsApp", "bg-green-50 text-green-700 ring-green-600/20"),
    "instagram": ("Instagram", "bg-pink-50 text-pink-700 ring-pink-600/20"),
}

CHANNEL_ICONS: dict[str, str] = {
    "whatsapp": (
        '<svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        '<path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2Zm0 18.2a8.2 8.2 0 0 1-4.2-1.2'
        'l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2Zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8-.2-.1-.4-.1-.6.1'
        'l-.8 1c-.1.2-.3.2-.5.1a6.7 6.7 0 0 1-3.3-2.9c-.2-.4.2-.4.7-1.3.1-.2 0-.3 0-.4l-.8-1.8c-.2-.5-.4-.4'
        '-.6-.4h-.5a1 1 0 0 0-.7.3 3 3 0 0 0-.9 2.2 5.2 5.2 0 0 0 1.1 2.7 11.9 11.9 0 0 0 4.6 4c1.7.7 2.4'
        '.8 3.2.7a2.8 2.8 0 0 0 1.8-1.3 2.3 2.3 0 0 0 .2-1.3c-.1-.1-.3-.2-.5-.3Z"/></svg>'
    ),
    "instagram": (
        '<svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="5"/>'
        '<circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor"/></svg>'
    ),
}

NOTE_TRANSLATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            rf"^{re.escape(SECURITY_NOTE_PREFIX)} Potential IDOR / customer mismatch\. "
            r"Customer (?P<customer>\d+) requested order (?P<order>\d+), which belongs to user "
            r"(?P<owner>\S+)\. Order contents concealed; identity verification required\.$"
        ),
        "GÜVENLİK: Olası IDOR / müşteri uyuşmazlığı. {customer} numaralı müşteri, "
        "{owner} numaralı kullanıcıya ait {order} numaralı siparişi sorguladı. Sipariş "
        "içeriği gizlendi; kimlik doğrulaması gereklidir.",
    ),
    (
        re.compile(r"^Order (?P<order>\d+) ownership verified for customer (?P<customer>\d+)\.$"),
        "{order} numaralı siparişin {customer} numaralı müşteriye ait olduğu doğrulandı.",
    ),
    (
        re.compile(r"^Order (?P<order>\d+) not found \(HTTP 404\)\.$"),
        "{order} numaralı sipariş bulunamadı (HTTP 404).",
    ),
    (
        re.compile(r"^Order lookup for (?P<order>\d+) failed \((?P<error>.*)\); manual check required\.$"),
        "{order} numaralı sipariş sorgusu başarısız oldu ({error}); manuel kontrol gereklidir.",
    ),
    (
        re.compile(r"^Order status requested without an order number\.$"),
        "Sipariş numarası belirtilmeden sipariş durumu soruldu.",
    ),
    (
        re.compile(
            r"^Possible adverse reaction reported\. Mandatory human handoff; no medical "
            r"advice or product recommendation given\.$"
        ),
        "Olası istenmeyen etki bildirimi. Zorunlu insan devri; tıbbi tavsiye veya ürün "
        "önerisi verilmedi.",
    ),
    (
        re.compile(r"^Return/complaint request\. Mandatory human handoff\.$"),
        "İade / şikâyet talebi. Zorunlu insan devri.",
    ),
    (
        re.compile(r"^Price inquiry\. Verify current price list before sending\.$"),
        "Fiyat talebi. Göndermeden önce güncel fiyat listesi doğrulanmalıdır.",
    ),
    (
        re.compile(
            r"^Product question\. Answer from official product data sheet only; no skin "
            r"diagnosis or personal recommendation\.$"
        ),
        "Ürün sorusu. Yalnızca resmi ürün bilgi föyüne dayanarak yanıtlanmalı; cilt "
        "teşhisi veya kişisel öneri yapılmamalıdır.",
    ),
    (
        re.compile(
            r"^Spam / suspicious link detected\. Do not reply or open links; consider "
            r"blocking the sender\.$"
        ),
        "Spam / şüpheli bağlantı tespit edildi. Yanıt verilmemeli, bağlantılar "
        "açılmamalı; göndericinin engellenmesi değerlendirilmelidir.",
    ),
    (
        re.compile(r"^General inquiry\. Answer with standard company information\.$"),
        "Genel talep. Standart şirket bilgileriyle yanıtlanmalıdır.",
    ),
)

SECONDARY_INTENT_PATTERN = re.compile(r"\s*Secondary intent: (?P<intent>[a-z-]+)\.$")


@dataclass(frozen=True)
class DashboardRow:
    id: int
    channel: str
    customer_id: int
    category: Category
    priority: Priority
    handoff: bool
    reply: str
    note: str
    is_security_violation: bool
    is_sensitive: bool

    def csv_record(self) -> list[str | int]:
        """Values in CSV_COLUMNS order, matching the talepler.csv export."""
        return [
            self.id,
            self.channel,
            self.customer_id,
            self.category.value,
            self.priority.value,
            "true" if self.handoff else "false",
            self.reply,
            self.note,
        ]


def translate_note(note: str) -> str:
    """Render the English internal note in Turkish; unknown formats are shown as-is."""
    suffix = ""
    secondary = SECONDARY_INTENT_PATTERN.search(note)
    if secondary:
        note = note[: secondary.start()]
        intent = secondary.group("intent")
        label = next(
            (CATEGORY_LABELS[c] for c in Category if c.value == intent), intent
        )
        suffix = f" İkincil niyet: {label}."

    for pattern, template in NOTE_TRANSLATIONS:
        match = pattern.match(note)
        if match:
            return template.format(**match.groupdict()) + suffix
    return note + suffix


def load_json_array(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path.name} must contain a JSON array")
    return data


def build_rows(messages: list[dict[str, Any]], tickets: list[dict[str, Any]]) -> list[DashboardRow]:
    messages_by_id = {message["id"]: message for message in messages}
    missing = [ticket["id"] for ticket in tickets if ticket["id"] not in messages_by_id]
    if missing:
        raise ValueError(f"Tickets without a source message: {missing}")

    rows: list[DashboardRow] = []
    for ticket in sorted(tickets, key=lambda item: item["id"]):
        message = messages_by_id[ticket["id"]]
        category = Category(ticket["konu"])
        rows.append(
            DashboardRow(
                id=ticket["id"],
                channel=str(message["kanal"]).lower(),
                customer_id=message["musteri_id"],
                category=category,
                priority=Priority(ticket["oncelik"]),
                handoff=bool(ticket["devret"]),
                reply=ticket["cevap_taslagi"],
                note=ticket["not"],
                is_security_violation=ticket["not"].startswith(SECURITY_NOTE_PREFIX),
                is_sensitive=category in HANDOFF_CATEGORIES,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# HTML fragments
# ---------------------------------------------------------------------------

def render_channel_badge(channel: str) -> str:
    label, style = CHANNEL_META.get(channel, (channel.title(), "bg-slate-100 text-slate-700 ring-slate-500/20"))
    icon = CHANNEL_ICONS.get(channel, "")
    return (
        f'<span class="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium '
        f'ring-1 ring-inset {style}">{icon}{escape(label)}</span>'
    )


def render_category_badge(category: Category) -> str:
    return (
        f'<span class="inline-flex whitespace-nowrap rounded-md px-2 py-1 text-xs font-medium '
        f'ring-1 ring-inset {CATEGORY_STYLES[category]}">{escape(CATEGORY_LABELS[category])}</span>'
    )


def render_priority_badge(priority: Priority) -> str:
    style, dot = PRIORITY_STYLES[priority]
    return (
        f'<span class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1 text-xs '
        f'font-bold tracking-wide ring-1 ring-inset {style}">'
        f'<span class="h-1.5 w-1.5 rounded-full {dot}"></span>{escape(PRIORITY_LABELS[priority])}</span>'
    )


def render_status_badge(handoff: bool) -> str:
    if handoff:
        return (
            '<span class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-rose-50 '
            'px-2.5 py-1 text-xs font-semibold text-rose-700 ring-1 ring-inset ring-rose-600/30">'
            '<span class="h-1.5 w-1.5 rounded-full bg-rose-500"></span>İnsana Yönlendir</span>'
        )
    return (
        '<span class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-emerald-50 '
        'px-2.5 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-600/20">'
        '<span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>Otomatik Yanıt</span>'
    )


def render_row(row: DashboardRow) -> str:
    if row.is_security_violation:
        row_class = "bg-rose-50/60 border-l-4 border-l-rose-500"
        flag = (
            '<span class="mt-1.5 inline-flex items-center gap-1 whitespace-nowrap rounded bg-rose-600 '
            'px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">'
            '&#9888; Güvenlik İhlali</span>'
        )
    elif row.is_sensitive:
        row_class = "bg-amber-50/60 border-l-4 border-l-amber-400"
        flag = (
            '<span class="mt-1.5 inline-flex items-center gap-1 whitespace-nowrap rounded bg-amber-500 '
            'px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">'
            'Hassas Konu</span>'
        )
    else:
        row_class = "border-l-4 border-l-transparent hover:bg-slate-50"
        flag = ""

    note_class = "text-rose-700 font-medium" if row.is_security_violation else "text-slate-500"
    return f"""
            <tr class="align-top {row_class}" data-id="{row.id}" data-devret="{str(row.handoff).lower()}" data-oncelik="{row.priority.value}">
              <td class="px-4 py-4 font-mono text-sm font-semibold text-slate-900">#{row.id}</td>
              <td class="px-4 py-4">{render_channel_badge(row.channel)}</td>
              <td class="px-4 py-4 font-mono text-sm text-slate-600">{row.customer_id}</td>
              <td class="px-4 py-4"><div class="flex flex-col items-start">{render_category_badge(row.category)}{flag}</div></td>
              <td class="px-4 py-4">{render_priority_badge(row.priority)}</td>
              <td class="px-4 py-4">{render_status_badge(row.handoff)}</td>
              <td class="px-4 py-4 text-sm leading-relaxed text-slate-700 whitespace-pre-line min-w-[18rem]">{escape(row.reply)}</td>
              <td class="px-4 py-4 text-xs leading-relaxed {note_class} min-w-[14rem]">{escape(translate_note(row.note))}</td>
            </tr>"""


def render_category_cards(rows: list[DashboardRow]) -> str:
    counts = Counter(row.category for row in rows)
    total = len(rows) or 1
    cards = []
    for category in CATEGORY_ORDER:
        count = counts.get(category, 0)
        percent = round(count * 100 / total)
        cards.append(
            f"""
          <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div class="flex items-center justify-between gap-2">
              {render_category_badge(category)}
              <span class="text-2xl font-bold tabular-nums text-slate-900">{count}</span>
            </div>
            <div class="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
              <div class="h-full rounded-full bg-slate-800" style="width: {percent}%"></div>
            </div>
            <p class="mt-1.5 text-xs text-slate-500">Toplam içindeki pay: %{percent}</p>
          </div>"""
        )
    return "".join(cards)


def render_security_details(rows: list[DashboardRow]) -> str:
    violations = [row for row in rows if row.is_security_violation]
    if not violations:
        return '<p class="mt-2 text-sm text-slate-500">Yetkisiz erişim girişimi tespit edilmedi.</p>'
    items = "".join(
        f'<li class="mt-1 text-sm text-rose-800"><span class="font-mono font-semibold">#{row.id}</span> '
        f"&middot; {escape(translate_note(row.note))}</li>"
        for row in violations
    )
    return f'<ul class="mt-2">{items}</ul>'


def render_high_priority_details(rows: list[DashboardRow]) -> str:
    high = [row for row in rows if row.priority is Priority.HIGH]
    if not high:
        return '<p class="mt-2 text-xs text-slate-500">Acil müdahale gerektiren vaka bulunmamaktadır.</p>'
    items = "".join(
        f'<li class="mt-1 text-xs text-slate-600"><span class="font-mono font-semibold text-rose-700">'
        f"#{row.id}</span> &middot; "
        f"{'Güvenlik ihlali (IDOR)' if row.is_security_violation else escape(CATEGORY_LABELS[row.category])}</li>"
        for row in high
    )
    return f'<ul class="mt-2">{items}</ul>'


def render_export_payload(rows: list[DashboardRow]) -> str:
    """Serialize rows for client-side CSV export, safe for embedding in a <script> element."""
    payload = {
        "columns": list(CSV_COLUMNS),
        "rows": {str(row.id): row.csv_record() for row in rows},
    }
    return (
        json.dumps(payload, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


PAGE_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nurederm &middot; Müşteri Talepleri Özeti</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
  </style>
</head>
<body class="min-h-screen bg-slate-100 text-slate-900 antialiased">
  <header class="border-b border-slate-200 bg-white">
    <div class="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-6 sm:flex-row sm:items-end sm:justify-between sm:px-6 lg:px-8">
      <div>
        <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">Nurederm &middot; Müşteri Deneyimi</p>
        <h1 class="mt-1 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">Müşteri Talepleri Yönetici Özeti</h1>
        <p class="mt-1 text-sm text-slate-500">WhatsApp ve Instagram kanallarından gelen mesajların otomatik sınıflandırma ve yanıt taslağı raporu.</p>
      </div>
      <p class="text-xs text-slate-500">Oluşturulma: <span class="font-medium text-slate-700">$generated_at</span></p>
    </div>
  </header>

  <main class="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6 lg:px-8">
    <section aria-labelledby="genel-bakis">
      <h2 id="genel-bakis" class="sr-only">Genel Bakış</h2>
      <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <p class="text-sm font-medium text-slate-500">İşlenen Toplam Mesaj</p>
          <p class="mt-2 text-4xl font-bold tabular-nums text-slate-900">$total</p>
          <p class="mt-2 text-xs text-slate-500">$auto_count mesaj otomatik yanıtlanabilir durumda</p>
        </div>
        <div class="rounded-2xl border border-amber-200 bg-white p-6 shadow-sm">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <p class="text-sm font-medium text-slate-500">İnsana Devredilen Talepler</p>
            <span class="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-800 ring-1 ring-inset ring-amber-600/30">Aksiyon Gerekli</span>
          </div>
          <p class="mt-2 text-4xl font-bold tabular-nums text-amber-600">$handoff_count</p>
          <p class="mt-2 text-xs text-slate-500">Uzman ekip incelemesi bekleyen pay: %$handoff_percent</p>
        </div>
        <div class="rounded-2xl border border-rose-200 bg-white p-6 shadow-sm">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <p class="text-sm font-medium text-slate-500">Yüksek Öncelikli Vakalar</p>
            <span class="rounded-full bg-rose-100 px-2.5 py-0.5 text-xs font-semibold text-rose-700 ring-1 ring-inset ring-rose-600/30">Acil</span>
          </div>
          <p class="mt-2 text-4xl font-bold tabular-nums text-rose-600">$high_priority_count</p>
          $high_priority_details
        </div>
        <div class="rounded-2xl border-2 border-rose-300 bg-rose-50 p-6 shadow-sm">
          <div class="flex items-center justify-between gap-2">
            <p class="text-sm font-semibold text-rose-800">Güvenlik İhlali / Engellenen IDOR</p>
            <span class="inline-flex h-8 w-8 items-center justify-center rounded-full bg-rose-600 text-white" aria-hidden="true">
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>
            </span>
          </div>
          <p class="mt-2 text-4xl font-bold tabular-nums text-rose-700">$violation_count</p>
          $security_details
        </div>
      </div>
    </section>

    <section aria-labelledby="kategori-dagilimi">
      <h2 id="kategori-dagilimi" class="text-lg font-semibold text-slate-900">Kategori Dağılımı</h2>
      <div class="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">$category_cards
      </div>
    </section>

    <section aria-labelledby="talep-detaylari" class="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div class="flex flex-col gap-4 border-b border-slate-200 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-6">
        <div>
          <h2 id="talep-detaylari" class="text-lg font-semibold text-slate-900">Talep Detayları</h2>
          <p class="text-sm text-slate-500">Yanıt taslakları gönderilmeden önce müşteri temsilcisi tarafından onaylanmalıdır.</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <div class="inline-flex flex-wrap gap-2" role="tablist" aria-label="Talep filtresi">
            <button type="button" role="tab" data-filter="all" data-slug="tumu" aria-selected="true" class="filter-btn rounded-lg px-3 py-2 text-sm font-medium">Tümü ($total)</button>
            <button type="button" role="tab" data-filter="true" data-slug="insana-devredilenler" aria-selected="false" class="filter-btn rounded-lg px-3 py-2 text-sm font-medium">İnsana Devredilenler ($handoff_count)</button>
            <button type="button" role="tab" data-filter="false" data-slug="dogrudan-yanitlananlar" aria-selected="false" class="filter-btn rounded-lg px-3 py-2 text-sm font-medium">Doğrudan Yanıtlananlar ($auto_count)</button>
          </div>
          <button type="button" id="csv-indir" class="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50">
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3v12m0 0-4-4m4 4 4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>
            CSV Olarak İndir
          </button>
        </div>
      </div>
      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-slate-200">
          <thead class="bg-slate-50">
            <tr class="whitespace-nowrap text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <th scope="col" class="px-4 py-3">ID</th>
              <th scope="col" class="px-4 py-3">Kanal</th>
              <th scope="col" class="px-4 py-3">Müşteri ID</th>
              <th scope="col" class="px-4 py-3">Konu</th>
              <th scope="col" class="px-4 py-3">Öncelik</th>
              <th scope="col" class="px-4 py-3">Durum</th>
              <th scope="col" class="px-4 py-3">Cevap Taslağı</th>
              <th scope="col" class="px-4 py-3">Dahili Not</th>
            </tr>
          </thead>
          <tbody id="talep-tablosu" class="divide-y divide-slate-100">$rows
          </tbody>
        </table>
      </div>
      <p id="bos-durum" class="hidden p-6 text-center text-sm text-slate-500">Bu filtreye uygun talep bulunmamaktadır.</p>
    </section>
  </main>

  <footer class="mx-auto max-w-7xl px-4 pb-8 text-xs text-slate-400 sm:px-6 lg:px-8">
    İstenmeyen etki ve iade / şikâyet talepleri, tıbbi ve hukuki güvenlik politikası gereği her zaman insana devredilir.
  </footer>

  <script type="application/json" id="talep-verisi">$export_payload</script>
  <script>
    (function () {
      var ACTIVE = ["bg-slate-900", "text-white", "shadow-sm"];
      var INACTIVE = ["bg-slate-100", "text-slate-700", "hover:bg-slate-200"];
      var buttons = document.querySelectorAll(".filter-btn");
      var rows = document.querySelectorAll("#talep-tablosu tr");
      var emptyState = document.getElementById("bos-durum");
      var downloadButton = document.getElementById("csv-indir");
      var exportData = JSON.parse(document.getElementById("talep-verisi").textContent);
      var activeSlug = "tumu";

      function visibleRows() {
        return Array.prototype.filter.call(rows, function (row) { return !row.classList.contains("hidden"); });
      }

      function applyFilter(filter) {
        var visible = 0;
        rows.forEach(function (row) {
          var show = filter === "all" || row.getAttribute("data-devret") === filter;
          row.classList.toggle("hidden", !show);
          if (show) { visible += 1; }
        });
        emptyState.classList.toggle("hidden", visible !== 0);
        downloadButton.disabled = visible === 0;
        buttons.forEach(function (button) {
          var isActive = button.getAttribute("data-filter") === filter;
          button.setAttribute("aria-selected", isActive ? "true" : "false");
          ACTIVE.forEach(function (cls) { button.classList.toggle(cls, isActive); });
          INACTIVE.forEach(function (cls) { button.classList.toggle(cls, !isActive); });
          if (isActive) { activeSlug = button.getAttribute("data-slug"); }
        });
      }

      function csvCell(value) {
        var text = value === null || value === undefined ? "" : String(value);
        return /[",\\r\\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
      }

      function downloadCsv() {
        var lines = [exportData.columns.map(csvCell).join(",")];
        visibleRows().forEach(function (row) {
          var record = exportData.rows[row.getAttribute("data-id")];
          if (record) { lines.push(record.map(csvCell).join(",")); }
        });
        var blob = new Blob(["\\uFEFF" + lines.join("\\r\\n") + "\\r\\n"], { type: "text/csv;charset=utf-8" });
        var url = URL.createObjectURL(blob);
        var link = document.createElement("a");
        link.href = url;
        link.download = "talepler-" + activeSlug + ".csv";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setTimeout(function () { URL.revokeObjectURL(url); }, 0);
      }

      buttons.forEach(function (button) {
        button.addEventListener("click", function () { applyFilter(button.getAttribute("data-filter")); });
      });
      downloadButton.addEventListener("click", downloadCsv);
      applyFilter("all");
    })();
  </script>
</body>
</html>
""")


def render_page(rows: list[DashboardRow], generated_at: datetime) -> str:
    total = len(rows)
    handoff_count = sum(1 for row in rows if row.handoff)
    violation_count = sum(1 for row in rows if row.is_security_violation)
    high_priority_count = sum(1 for row in rows if row.priority is Priority.HIGH)
    return PAGE_TEMPLATE.substitute(
        generated_at=generated_at.strftime("%d.%m.%Y %H:%M"),
        total=total,
        handoff_count=handoff_count,
        auto_count=total - handoff_count,
        handoff_percent=round(handoff_count * 100 / total) if total else 0,
        violation_count=violation_count,
        security_details=render_security_details(rows),
        high_priority_count=high_priority_count,
        high_priority_details=render_high_priority_details(rows),
        category_cards=render_category_cards(rows),
        rows="".join(render_row(row) for row in rows),
        export_payload=render_export_payload(rows),
    )


def main() -> int:
    try:
        rows = build_rows(load_json_array(INPUT_PATH), load_json_array(OUTPUT_PATH))
    except (OSError, ValueError, KeyError) as exc:
        print(f"Dashboard generation failed: {exc}", file=sys.stderr)
        return 1
    HTML_PATH.write_text(render_page(rows, datetime.now()), encoding="utf-8")
    print(f"Wrote {HTML_PATH.name} with {len(rows)} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
