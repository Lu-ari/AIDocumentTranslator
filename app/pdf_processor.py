"""
PDF metin çıkarma modülü.
PyMuPDF (fitz) kullanarak PDF'den yapısal metin çıkarır.
Tablo algılama, başlık/paragraf ayrıştırma yapar.
"""

import fitz  # PyMuPDF
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class TableData:
    """Bir tablo verisini temsil eder."""
    headers: list[str]
    rows: list[list[str]]
    bbox: tuple = (0, 0, 0, 0)


@dataclass
class PageContent:
    page_number: int
    text: str
    blocks: list[dict]
    tables: list[TableData] = field(default_factory=list)
    has_tables: bool = False


@dataclass
class PDFContent:
    filename: str
    total_pages: int
    pages: list[PageContent]
    metadata: dict


def extract_text_from_pdf(pdf_path: str | Path) -> PDFContent:
    """
    PDF'den sayfa bazlı metin ve tablo çıkarır.
    Tablo algılama ile yapısal veriyi korur.
    """
    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))

    pages = []
    for page_num in range(len(doc)):
        page = doc[page_num]

        # ── Tablo algılama ──
        tables_data = []
        table_rects = []
        try:
            tabs = page.find_tables()
            for tab in tabs:
                extracted = tab.extract()
                if not extracted or len(extracted) == 0:
                    continue

                # ── Sahte tablo filtresi ──
                # 1) Tek hücreli "tablolar" atla (sayfa numarası barları vb.)
                total_cells = sum(len(r) for r in extracted)
                if total_cells <= 2:
                    continue

                # 2) Sadece 1 satır + 1 sütun = tablo değil
                if len(extracted) <= 1 and len(extracted[0]) <= 1:
                    continue

                # 3) Tüm hücreleri birleştirip URL kontrolü
                all_text = " ".join(
                    str(c).strip() for r in extracted for c in r if c
                )
                if _looks_like_url(all_text):
                    continue

                # 4) Tüm hücreler boş veya sadece sayı ise sahte tablo
                non_empty = [str(c).strip() for r in extracted for c in r if c and str(c).strip()]
                if len(non_empty) <= 1:
                    continue

                headers = [str(c).strip() if c else "" for c in extracted[0]]
                rows = []
                for row in extracted[1:]:
                    rows.append([str(c).strip() if c else "" for c in row])
                table_rects.append(fitz.Rect(tab.bbox))
                tables_data.append(TableData(
                    headers=headers,
                    rows=rows,
                    bbox=tab.bbox,
                ))
        except Exception:
            pass  # Tablo bulunamazsa düz metin ile devam

        # ── Metin blokları çıkarma (tablo dışı) ──
        blocks_raw = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        structured_blocks = []
        page_text_parts = []

        for block in blocks_raw:
            if block["type"] != 0:  # Sadece metin blokları
                continue

            # Bu blok bir tablonun içinde mi?
            block_rect = fitz.Rect(block["bbox"])
            in_table = any(
                tr.contains(block_rect) or tr.intersects(block_rect)
                for tr in table_rects
            )
            if in_table:
                continue  # Tablo verisi ayrı taşınıyor

            block_text = ""
            block_font_size = 0
            block_is_bold = False

            for line in block["lines"]:
                line_text = ""
                for span in line["spans"]:
                    line_text += span["text"]
                    block_font_size = max(block_font_size, span["size"])
                    if "bold" in span["font"].lower():
                        block_is_bold = True
                block_text += line_text + "\n"

            block_text = block_text.strip()
            if block_text:
                # Unicode madde işaretlerini ASCII'ye dönüştür
                block_text = _sanitize_bullets(block_text)
                structured_blocks.append({
                    "text": block_text,
                    "font_size": round(block_font_size, 1),
                    "is_bold": block_is_bold,
                    "bbox": block["bbox"],
                })
                page_text_parts.append(block_text)

        # Tablo verilerini de metin temsiline ekle (çeviri için)
        for tbl in tables_data:
            table_text = _table_to_text(tbl)
            page_text_parts.append(table_text)

        full_text = "\n\n".join(page_text_parts)
        pages.append(PageContent(
            page_number=page_num + 1,
            text=full_text,
            blocks=structured_blocks,
            tables=tables_data,
            has_tables=len(tables_data) > 0,
        ))

    metadata = doc.metadata or {}
    total_pages = len(doc)
    doc.close()

    return PDFContent(
        filename=pdf_path.name,
        total_pages=total_pages,
        pages=pages,
        metadata=metadata,
    )


def _table_to_text(table: TableData) -> str:
    """
    Tablo verisini yapısal metin formatına dönüştürür.
    LLM'in tablo yapısını anlaması için Markdown tablo formatı kullanır.
    """
    lines = []
    lines.append("[TABLE_START]")

    # Header
    if table.headers and any(h for h in table.headers):
        lines.append("| " + " | ".join(table.headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(table.headers)) + " |")

    # Rows
    for row in table.rows:
        # Boş satırları atla
        if not any(cell.strip() for cell in row):
            continue
        lines.append("| " + " | ".join(row) + " |")

    lines.append("[TABLE_END]")
    return "\n".join(lines)


def split_text_into_chunks(text: str, max_chars: int = 3000) -> list[str]:
    """
    Büyük metni anlamlı parçalara böler.
    Tablo bloklarını bölmez, paragraf sınırlarını korur.
    """
    if len(text) <= max_chars:
        return [text]

    # Tablo bloklarını koruyarak böl
    parts = []
    current = ""
    in_table = False

    for line in text.split("\n"):
        if "[TABLE_START]" in line:
            in_table = True
            if current.strip():
                parts.append(("text", current.strip()))
                current = ""
            current = line + "\n"
            continue
        elif "[TABLE_END]" in line:
            in_table = False
            current += line + "\n"
            parts.append(("table", current.strip()))
            current = ""
            continue

        if in_table:
            current += line + "\n"
        else:
            current += line + "\n"

    if current.strip():
        parts.append(("text", current.strip()))

    # Parçaları chunk'lara birleştir
    chunks = []
    current_chunk = ""

    for part_type, part_text in parts:
        if part_type == "table":
            # Tablo bloğunu bölme, ayrı chunk yap
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
                current_chunk = ""
            chunks.append(part_text)
        else:
            paragraphs = part_text.split("\n\n")
            for para in paragraphs:
                if len(current_chunk) + len(para) + 2 <= max_chars:
                    current_chunk += ("\n\n" + para) if current_chunk else para
                else:
                    if current_chunk.strip():
                        chunks.append(current_chunk.strip())
                    if len(para) > max_chars:
                        # Çok uzun paragrafı cümle bazında böl
                        for sub in _split_into_sentences(para):
                            if len(current_chunk) + len(sub) + 1 <= max_chars:
                                current_chunk += (" " + sub) if current_chunk else sub
                            else:
                                if current_chunk.strip():
                                    chunks.append(current_chunk.strip())
                                current_chunk = sub
                    else:
                        current_chunk = para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks if chunks else [text]


def _split_into_sentences(text: str) -> list[str]:
    """Metni cümlelere ayırır."""
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s for s in sentences if s.strip()]


def _looks_like_url(text: str) -> bool:
    """Metnin bir URL olup olmadığını kontrol eder."""
    import re
    text = text.strip()
    # URL kalıpları
    if re.search(r'https?://', text):
        return True
    if re.search(r'www\.', text):
        return True
    if re.search(r'\.[a-z]{2,4}/', text):
        return True
    return False


def _sanitize_bullets(text: str) -> str:
    """Unicode madde işaretlerini ASCII karakterlere dönüştürür."""
    replacements = {
        "\u25cf": "* ",   # ● dolu daire
        "\u25cb": "  o ",  # ○ boş daire
        "\u25a0": "* ",   # ■
        "\u25ba": "> ",   # ►
        "\u2022": "* ",   # •
        "\u2023": "> ",   # ‣
        "\u25e6": "  o ",  # ◦
        "\u2043": "- ",   # ⁃
        "\u27a4": "> ",   # ➤
        "\u2192": "->",   # →
        "\u2713": "[x]",  # ✓
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text
