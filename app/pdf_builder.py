"""
Çevrilmiş metinden PDF oluşturma modülü.
Geniş tablolar için landscape, metin sarma (word-wrap),
ve akıllı sütun bölme destekli.
"""

import re
import math
from fpdf import FPDF
from pathlib import Path


class TranslatedPDFBuilder(FPDF):

    def __init__(self, orientation="P"):
        super().__init__(orientation=orientation)
        self.set_auto_page_break(auto=True, margin=18)

    def header(self):
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(170, 170, 170)
        self.cell(0, 6, "AI Document Translator", align="C")
        self.ln(2)
        self.set_draw_color(220, 220, 220)
        self.line(10, self.get_y(), self.w - 10, self.get_y())
        self.ln(3)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(170, 170, 170)
        self.cell(0, 8, f"Page {self.page_no()}/{{nb}}", align="C")


def _safe(text: str) -> str:
    """Latin-1 uyumlu hale getirir."""
    replacements = {
        "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "--",
        "\u2026": "...", "\u00a0": " ", "\u200b": "",
        "\u0131": "i", "\u015f": "s", "\u011f": "g",
        "\u00e7": "c", "\u00fc": "u", "\u00f6": "o",
        "\u0130": "I", "\u015e": "S", "\u011e": "G",
        "\u00c7": "C", "\u00dc": "U", "\u00d6": "O",
        # Madde işaretleri
        "\u25cf": "*",   # ● (dolu daire)
        "\u25cb": "o",   # ○ (boş daire)
        "\u25a0": "*",   # ■
        "\u25ba": ">",   # ►
        "\u2022": "*",   # • (bullet)
        "\u2023": ">",   # ‣
        "\u25e6": "o",   # ◦
        "\u2043": "-",   # ⁃
        "\u27a4": ">",   # ➤
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ═══════════════════════════════════════════════════════════════
# Metin ve tablo bloklarını ayrıştırma
# ═══════════════════════════════════════════════════════════════

def _parse_blocks(text: str) -> list[tuple[str, object]]:
    """Çevrilmiş metni metin ve tablo bloklarına ayırır."""
    blocks = []
    lines = text.split("\n")
    current_text = []
    table_lines = []
    in_table = False

    def flush_text():
        nonlocal current_text
        joined = "\n".join(current_text).strip()
        if joined:
            blocks.append(("text", joined))
        current_text = []

    def flush_table():
        nonlocal table_lines, in_table
        if table_lines:
            td = _parse_md_table(table_lines)
            if td:
                blocks.append(("table", td))
        table_lines = []
        in_table = False

    for line in lines:
        s = line.strip()

        if s == "[TABLE_START]":
            flush_text()
            in_table = True
            table_lines = []
            continue
        elif s == "[TABLE_END]":
            flush_table()
            continue

        if in_table:
            table_lines.append(line)
            continue

        # Markdown tablo algılama: | ... | formatında satırlar
        if s.startswith("|") and s.endswith("|") and s.count("|") >= 3:
            if not table_lines:
                flush_text()
            table_lines.append(line)
            in_table = True
            continue

        # Tablo satırı bitti mi?
        if table_lines and not (s.startswith("|") and s.endswith("|")):
            flush_table()

        current_text.append(line)

    if table_lines:
        flush_table()
    flush_text()

    return blocks if blocks else [("text", text)]


def _parse_md_table(lines: list[str]) -> dict | None:
    """Markdown tablo satırlarından header+rows parse eder."""
    data_rows = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        # Separator satırını atla
        if re.match(r'^\|[\s\-:| ]+\|$', s):
            clean = s.replace("|", "").replace("-", "").replace(":", "").strip()
            if not clean:
                continue
        cells = [c.strip() for c in s.split("|")]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if cells:
            data_rows.append(cells)

    if not data_rows:
        return None

    # Sahte tablo filtresi: tek satırlık veya sadece sayılardan oluşan "tablolar"
    all_cells = [c for row in data_rows for c in row]
    non_empty_cells = [c for c in all_cells if c.strip()]
    if len(non_empty_cells) <= 1:
        return None  # Tek hücreli = tablo değil
    # Tüm hücreler sadece sayı veya boşsa tablo değil (sayfa numarası barları)
    if all(c.strip().isdigit() or not c.strip() for c in all_cells):
        return None

    return {"headers": data_rows[0], "rows": data_rows[1:]}


# ═══════════════════════════════════════════════════════════════
# Tablo render — çok sütunlu tabloları bölmeli render
# ═══════════════════════════════════════════════════════════════

def _get_cell_height(pdf: FPDF, text: str, col_w: float, font_size: float) -> float:
    """Bir hücrenin sarma sonrası yüksekliğini hesaplar."""
    pdf.set_font("Helvetica", "", font_size)
    # Karakter genişliği tahmini
    char_w = font_size * 0.45
    if col_w < 5:
        return font_size * 0.5
    chars_per_line = max(1, int(col_w / char_w))
    num_lines = max(1, math.ceil(len(text) / chars_per_line))
    return num_lines * (font_size * 0.5)


def _render_table_on_pdf(pdf: FPDF, headers: list[str], rows: list[list[str]]):
    """
    Tabloyu PDF'e render eder.
    Çok geniş tablolarda sütunları gruplara böler.
    """
    num_cols = len(headers) if headers else (len(rows[0]) if rows else 0)
    if num_cols == 0:
        return

    usable_w = pdf.w - 20  # margin
    min_col_w = 18  # minimum sütun genişliği
    max_cols_per_page = max(1, int(usable_w / min_col_w))

    if num_cols <= max_cols_per_page:
        # Tek seferde render et
        _render_table_section(pdf, headers, rows, usable_w)
    else:
        # İlk 2-3 sütun sabit (Serial, BSN, Gender gibi), geri kalanı bölümlere ayır
        # İlk sütun referans sütunu
        fixed_cols = min(2, num_cols)
        data_cols = list(range(fixed_cols, num_cols))

        # Her bölümde kaç data sütunu sığar
        fixed_w = fixed_cols * 15
        remaining_w = usable_w - fixed_w
        data_cols_per_section = max(1, int(remaining_w / min_col_w))

        for chunk_start in range(0, len(data_cols), data_cols_per_section):
            chunk_end = min(chunk_start + data_cols_per_section, len(data_cols))
            col_indices = list(range(fixed_cols)) + data_cols[chunk_start:chunk_end]

            section_headers = [headers[i] if i < len(headers) else "" for i in col_indices]
            section_rows = []
            for row in rows:
                section_rows.append([row[i] if i < len(row) else "" for i in col_indices])

            if chunk_start > 0:
                pdf.ln(3)
                pdf.set_font("Helvetica", "I", 7)
                pdf.set_text_color(140, 140, 140)
                pdf.cell(0, 5, "(continued)", ln=True)
                pdf.ln(1)

            _render_table_section(pdf, section_headers, section_rows, usable_w)


def _render_table_section(
    pdf: FPDF,
    headers: list[str],
    rows: list[list[str]],
    total_w: float,
):
    """Tek bir tablo bölümünü render eder (word-wrap destekli)."""
    num_cols = len(headers)
    if num_cols == 0:
        return

    # Font boyutu — sütun sayısına göre küçült
    if num_cols <= 5:
        font_size = 8
    elif num_cols <= 8:
        font_size = 7
    elif num_cols <= 12:
        font_size = 6
    else:
        font_size = 5

    line_h = font_size * 0.55
    cell_padding = 1

    # ── Sütun genişliklerini hesapla ──
    col_widths = _smart_col_widths(headers, rows, total_w, num_cols, font_size)

    # ── Header ──
    if headers and any(h.strip() for h in headers):
        _render_header_row(pdf, headers, col_widths, font_size, line_h)

    # ── Veri satırları ──
    pdf.set_font("Helvetica", "", font_size)
    pdf.set_text_color(30, 30, 30)

    for i, row in enumerate(rows):
        # Boş satır atla
        if not any((row[j] if j < len(row) else "").strip() for j in range(num_cols)):
            continue

        # Satır yüksekliğini hesapla (en uzun hücreye göre)
        row_h = line_h + 2 * cell_padding
        for j in range(num_cols):
            cell_text = _safe(row[j]) if j < len(row) else ""
            h = _get_cell_height(pdf, cell_text, col_widths[j], font_size)
            row_h = max(row_h, h + 2 * cell_padding)
        row_h = min(row_h, 25)  # Max satır yüksekliği

        # Sayfa taşması
        if pdf.get_y() + row_h > pdf.h - 20:
            pdf.add_page()
            if headers and any(h.strip() for h in headers):
                _render_header_row(pdf, headers, col_widths, font_size, line_h)
            pdf.set_font("Helvetica", "", font_size)
            pdf.set_text_color(30, 30, 30)

        # Zebra arka plan
        fill_color = (245, 245, 250) if i % 2 == 0 else (255, 255, 255)
        pdf.set_fill_color(*fill_color)

        x_start = pdf.get_x()
        y_start = pdf.get_y()

        for j in range(num_cols):
            cell_text = _safe(row[j]) if j < len(row) else ""
            x = x_start + sum(col_widths[:j])
            pdf.set_xy(x, y_start)

            # Arka plan + çerçeve çiz
            pdf.rect(x, y_start, col_widths[j], row_h, style="DF")

            # Metin yaz (kırpma ile)
            pdf.set_xy(x + 0.5, y_start + cell_padding)
            # multi_cell yerine — metni sütun genişliğine sığacak şekilde kırp
            _write_cell_text(pdf, cell_text, col_widths[j] - 1, row_h - 2 * cell_padding, font_size)

        pdf.set_xy(x_start, y_start + row_h)

    pdf.ln(4)


def _render_header_row(pdf, headers, col_widths, font_size, line_h):
    """Tablo header satırını render eder."""
    pdf.set_font("Helvetica", "B", font_size)
    pdf.set_fill_color(35, 65, 130)
    pdf.set_text_color(255, 255, 255)
    pdf.set_draw_color(35, 65, 130)

    header_h = line_h + 4
    # Header yüksekliği — sarma gerekebilir
    for j, h in enumerate(headers):
        safe_h = _safe(h)
        ch = _get_cell_height(pdf, safe_h, col_widths[j], font_size)
        header_h = max(header_h, ch + 4)
    header_h = min(header_h, 20)

    x_start = pdf.get_x()
    y_start = pdf.get_y()

    for j, h in enumerate(headers):
        x = x_start + sum(col_widths[:j])
        pdf.set_xy(x, y_start)
        pdf.rect(x, y_start, col_widths[j], header_h, style="DF")
        pdf.set_xy(x + 0.5, y_start + 1)
        _write_cell_text(pdf, _safe(h), col_widths[j] - 1, header_h - 2, font_size)

    pdf.set_xy(x_start, y_start + header_h)
    pdf.set_draw_color(200, 200, 200)


def _write_cell_text(pdf, text: str, max_w: float, max_h: float, font_size: float):
    """Hücreye metin yazar, sığmazsa sardırır veya kırpar."""
    if not text:
        return
    pdf.set_font("Helvetica", pdf.font_style, font_size)
    char_w = font_size * 0.42
    chars_per_line = max(1, int(max_w / char_w))
    line_h = font_size * 0.5

    # Metni satırlara böl
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test = (current_line + " " + word).strip() if current_line else word
        if len(test) <= chars_per_line:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            # Kelime tek başına çok uzunsa kırp
            if len(word) > chars_per_line:
                lines.append(word[:chars_per_line - 1] + ".")
            else:
                current_line = word
                continue
            current_line = ""
    if current_line:
        lines.append(current_line)

    # Satır sayısını max_h'ye göre sınırla
    max_lines = max(1, int(max_h / line_h))
    lines = lines[:max_lines]

    x = pdf.get_x()
    y = pdf.get_y()
    for k, line in enumerate(lines):
        pdf.set_xy(x, y + k * line_h)
        pdf.cell(max_w, line_h, line)


def _smart_col_widths(
    headers: list[str],
    rows: list[list[str]],
    total_w: float,
    num_cols: int,
    font_size: float,
) -> list[float]:
    """İçerik uzunluğuna göre akıllı sütun genişliği hesaplar."""
    char_w = font_size * 0.45
    min_w = max(8, font_size * 3)

    # Her sütunun max içerik genişliğini bul
    max_content_w = []
    for j in range(num_cols):
        max_len = len(headers[j]) if j < len(headers) else 3
        for row in rows[:20]:  # İlk 20 satıra bak (performans)
            if j < len(row):
                max_len = max(max_len, len(row[j]))
        # Karakter genişliğine çevir
        w = max(min_w, min(max_len * char_w, total_w * 0.4))  # Tek sütun max %40
        max_content_w.append(w)

    # Toplam genişliğe normalize et
    total_content = sum(max_content_w)
    if total_content <= 0:
        return [total_w / num_cols] * num_cols

    widths = []
    for w in max_content_w:
        normalized = max(min_w, (w / total_content) * total_w)
        widths.append(normalized)

    # Son normalize — tam toplama eşitle
    s = sum(widths)
    widths = [w * total_w / s for w in widths]

    return widths


# ═══════════════════════════════════════════════════════════════
# Metin render
# ═══════════════════════════════════════════════════════════════

def _render_text_block(pdf: FPDF, text: str):
    """Normal metin paragrafları render eder."""
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(30, 30, 30)

    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        safe = _safe(paragraph)

        # Başlık (tamamen büyük harf ve kısa)
        if paragraph.isupper() and len(paragraph) < 80 and "\n" not in paragraph:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(40, 40, 40)
            pdf.cell(0, 7, safe, ln=True)
            pdf.ln(1)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(30, 30, 30)
        elif paragraph.startswith(("1-)", "2-)", "3-)", "4-)", "5-)")):
            pdf.set_font("Helvetica", "", 8.5)
            pdf.multi_cell(0, 5, safe)
            pdf.ln(2)
            pdf.set_font("Helvetica", "", 9)
        else:
            pdf.multi_cell(0, 5, safe)
            pdf.ln(2)


# ═══════════════════════════════════════════════════════════════
# Üst düzey PDF oluşturma
# ═══════════════════════════════════════════════════════════════

def build_translated_pdf(
    translated_pages: list[dict],
    output_path: str | Path,
    original_filename: str = "",
) -> Path:
    output_path = Path(output_path)

    # Tablo genişliğine göre orientation belirle
    needs_landscape = _check_needs_landscape(translated_pages)
    orientation = "L" if needs_landscape else "P"

    pdf = TranslatedPDFBuilder(orientation=orientation)
    pdf.alias_nb_pages()

    # Kapak sayfası
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(40, 40, 40)
    pdf.ln(35)
    pdf.cell(0, 14, "Translated Document", align="C", ln=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 13)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, "Turkish to English Translation", align="C", ln=True)
    if original_filename:
        pdf.ln(4)
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 8, f"Source: {_safe(original_filename)}", align="C", ln=True)
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 7, "Powered by Local AI Translation Engine", align="C", ln=True)
    pdf.cell(0, 7, f"Total pages translated: {len(translated_pages)}", align="C", ln=True)

    # Çevrilmiş sayfaları ekle
    for page_data in translated_pages:
        translated = page_data.get("translated", "")
        if not translated.strip():
            continue

        pdf.add_page()
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 7, f"Original Page {page_data['page_number']}", ln=True)
        pdf.ln(2)

        blocks = _parse_blocks(translated)
        for block_type, content in blocks:
            if block_type == "table":
                _render_table_on_pdf(pdf, content["headers"], content["rows"])
            else:
                _render_text_block(pdf, content)

    pdf.output(str(output_path))
    return output_path


def build_bilingual_pdf(
    translated_pages: list[dict],
    output_path: str | Path,
) -> Path:
    output_path = Path(output_path)

    needs_landscape = _check_needs_landscape(translated_pages)
    orientation = "L" if needs_landscape else "P"

    pdf = TranslatedPDFBuilder(orientation=orientation)
    pdf.alias_nb_pages()

    for page_data in translated_pages:
        original = page_data.get("original", "")
        translated = page_data.get("translated", "")
        if not original.strip() and not translated.strip():
            continue

        pdf.add_page()

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(180, 60, 60)
        pdf.cell(0, 7, f"ORIGINAL (Page {page_data['page_number']})", ln=True)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_text_color(80, 80, 80)
        pdf.multi_cell(0, 4, _safe(original[:2500]))

        pdf.ln(3)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), pdf.w - 10, pdf.get_y())
        pdf.ln(3)

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(60, 60, 180)
        pdf.cell(0, 7, "TRANSLATION", ln=True)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 4, _safe(translated[:2500]))

    pdf.output(str(output_path))
    return output_path


def _check_needs_landscape(translated_pages: list[dict]) -> bool:
    """Tabloda 6+ sütun varsa landscape moda geç."""
    for page_data in translated_pages:
        text = page_data.get("translated", "")
        blocks = _parse_blocks(text)
        for btype, content in blocks:
            if btype == "table":
                num_cols = len(content.get("headers", []))
                if num_cols >= 6:
                    return True
    return False
