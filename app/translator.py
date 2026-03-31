"""
Çeviri motoru — Tamamen ÜCRETSİZ, yerel çalışır.

Desteklenen motorlar:
1. Ollama  → Yerel LLM (qwen2.5, gemma3 vb.)
2. MarianMT → HuggingFace Helsinki-NLP/opus-mt-tr-en

İyileştirmeler:
- Resmi belge terminoloji sözlüğü (glossary)
- Tablo yapısını koruyan çeviri
- Bağlam-duyarlı chunk çevirisi
- Çift geçişli doğrulama (Ollama)
"""

import asyncio
import logging
import re
from abc import ABC, abstractmethod

from app.config import (
    TRANSLATION_ENGINE,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    MARIAN_MODEL_NAME,
    MAX_CHUNK_CHARS,
)
from app.pdf_processor import split_text_into_chunks

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Resmi belge terminoloji sözlüğü
# ═══════════════════════════════════════════════════════════════

OFFICIAL_GLOSSARY = """
MANDATORY TERMINOLOGY — You MUST use these exact translations for Turkish official/legal terms:

Nüfus Kayıt Örneği = Population Register Extract (Civil Registry Extract)
Nüfus Cüzdanı = Identity Card
T.C. Kimlik No / T.C. Kimlik Numarası = T.R. Identity Number
Tasdik / Tasdiki = Authentication / Certified by (NEVER use "consecration")
Konsolosluk Tasdiki = Consular Authentication
Nüfus Müdürlüğü = Civil Registry Office / Population Directorate
e-Devlet Kapısı = e-Government Portal
Belge Doğrulama = Document Verification

Sıra / Sıra No = Serial No. / Order No.
BSN (Birey Sıra No) = ISN (Individual Serial No.)
Cilt No = Volume No.
Hane No = Household No.
C (Cinsiyet) = G (Gender)
E (Erkek) = M (Male)
K (Kadın) = F (Female)
Yakınlık Derecesi = Relationship (Kinship)
Kendisi = Self

Adı / Ad = First Name / Given Name
Soyadı / Soyad = Surname / Family Name
Baba Adı = Father's Name
Ana Adı = Mother's Name
Doğum Yeri ve Tarihi = Place and Date of Birth
Medeni Hali = Marital Status
Din = Religion
Tescil Tarihi = Registration Date
Olaylar ve Tarihleri = Events and Dates
Düşünceler = Remarks / Notes (NEVER use "thoughts")

Bekar = Single
Evli = Married
Dul = Widowed
Boşanmış = Divorced
Sağ = Alive
Ölüm = Death
Evlenme = Marriage
Boşanma = Divorce

İl = Province
İlçe = District
Mahalle / Köy = Neighborhood / Village
Cilt = Volume
Aile Sıra No = Family Serial No.

5490 Sayılı Nüfus Hizmetleri Kanunu = Population Services Law No. 5490

Gelin olarak gelmiştir = Registered as a bride (married into the family)
"""


def _build_system_prompt():
    return (
        "You are an expert sworn translator specializing in Turkish-to-English "
        "translation of official government documents, civil registry records, "
        "legal certificates, and formal correspondence.\n\n"
        + OFFICIAL_GLOSSARY +
        "\n\nTRANSLATION RULES:\n"
        "1. ACCURACY: Preserve the EXACT meaning. Never omit, add, or alter information.\n"
        "2. TERMINOLOGY: ALWAYS use the glossary terms above. These are legally established translations.\n"
        "3. PROPER NOUNS: Keep Turkish names, places, and organizations exactly as they appear "
        "(e.g., ÜSKÜDAR stays USKUDAR).\n"
        "4. NUMBERS & DATES: Keep all numbers, dates, ID numbers in their EXACT original format.\n"
        "5. TABLE FORMAT: If the source contains [TABLE_START]...[TABLE_END] markers, "
        "translate the cell contents but preserve the EXACT Markdown table structure "
        "(pipes | and dashes ---). Do NOT restructure or reformat tables.\n"
        "6. ABBREVIATIONS: Keep T.C., BSN, etc. and add English equivalent in parentheses only on first occurrence.\n"
        "7. FORMAT: Maintain the original paragraph structure, line breaks, bullet points, and numbering exactly.\n"
        "8. OUTPUT: Return ONLY the translated text. No explanations, no notes, no commentary.\n"
        "9. ALREADY ENGLISH: If text is already in English, keep it as-is.\n"
        "10. BLANK CELLS: Keep '---' as '---' in tables."
    )


def _build_verification_prompt():
    return (
        "You are a certified bilingual Turkish-English legal document reviewer.\n\n"
        + OFFICIAL_GLOSSARY +
        "\n\nCompare the original Turkish text with its English translation. Check for:\n"
        "1. Missing content — any sentence, field, or data point not translated\n"
        "2. Added content — anything not in the original\n"
        "3. Terminology errors — especially official terms (check glossary above)\n"
        "4. Table structure — tables must keep their Markdown format with | pipes\n"
        "5. Name/number accuracy — all names, dates, ID numbers must be exact\n\n"
        "If the translation is fully accurate, respond with EXACTLY: VERIFIED\n"
        "If there are ANY issues, provide the COMPLETE corrected English translation only. No explanations."
    )


# ═══════════════════════════════════════════════════════════════
# Çeviri motor arayüzü
# ═══════════════════════════════════════════════════════════════

class TranslationEngine(ABC):
    @abstractmethod
    async def translate(self, text: str, context: str = "") -> str: ...

    @abstractmethod
    async def verify(self, original: str, translation: str) -> str: ...


# ═══════════════════════════════════════════════════════════════
# OLLAMA motoru
# ═══════════════════════════════════════════════════════════════

class OllamaEngine(TranslationEngine):
    def __init__(self):
        import httpx
        self.client = httpx.AsyncClient(base_url=OLLAMA_BASE_URL, timeout=600)
        self.model = OLLAMA_MODEL
        self.system_prompt = _build_system_prompt()
        self.verify_prompt = _build_verification_prompt()

    async def translate(self, text: str, context: str = "", max_retries: int = 3) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
        ]

        # Bağlamı ayrı bir assistant mesajı olarak ver (LLM kopyalamasın)
        if context:
            messages.append({
                "role": "assistant",
                "content": context,
            })

        messages.append({
            "role": "user",
            "content": (
                "Translate the following Turkish text to English. "
                "Return ONLY the English translation, nothing else.\n\n"
                + text
            ),
        })

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.05,
                "num_predict": 4096,
                "top_p": 0.9,
                "repeat_penalty": 1.1,
            },
        }

        for attempt in range(max_retries):
            try:
                resp = await self.client.post("/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["message"]["content"].strip()
            except Exception as e:
                logger.warning(f"Ollama çeviri denemesi {attempt + 1} başarısız: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise RuntimeError(f"Ollama çeviri başarısız: {e}")

    async def verify(self, original: str, translation: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.verify_prompt},
                {
                    "role": "user",
                    "content": (
                        f"ORIGINAL TURKISH TEXT:\n{original}\n\n"
                        f"ENGLISH TRANSLATION:\n{translation}\n\n"
                        "Review carefully and respond."
                    ),
                },
            ],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 4096},
        }

        try:
            resp = await self.client.post("/api/chat", json=payload)
            resp.raise_for_status()
            result = resp.json()["message"]["content"].strip()
            if "VERIFIED" in result and len(result) < 20:
                return translation
            logger.info("Çeviri doğrulama sonrası düzeltildi")
            return result
        except Exception as e:
            logger.warning(f"Doğrulama başarısız, orijinal çeviri kullanılıyor: {e}")
            return translation


# ═══════════════════════════════════════════════════════════════
# MarianMT motoru (sıfır kurulum, sadece pip install)
# ═══════════════════════════════════════════════════════════════

class MarianEngine(TranslationEngine):
    _model = None
    _tokenizer = None

    def _load_model(self):
        if MarianEngine._model is None:
            logger.info(f"MarianMT model yükleniyor: {MARIAN_MODEL_NAME} (ilk sefer)")
            from transformers import MarianMTModel, MarianTokenizer
            MarianEngine._tokenizer = MarianTokenizer.from_pretrained(MARIAN_MODEL_NAME)
            MarianEngine._model = MarianMTModel.from_pretrained(MARIAN_MODEL_NAME)
            logger.info("MarianMT model hazır")

    async def translate(self, text: str, context: str = "") -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._translate_sync, text)

    def _translate_sync(self, text: str) -> str:
        self._load_model()
        import re
        sentences = re.split(r'(?<=[.!?;:])\s+', text)
        translated_parts = []

        batch_size = 8
        for i in range(0, len(sentences), batch_size):
            batch = sentences[i:i + batch_size]
            inputs = MarianEngine._tokenizer(
                batch, return_tensors="pt", padding=True, truncation=True, max_length=512
            )
            outputs = MarianEngine._model.generate(**inputs, num_beams=4, max_length=512)
            for out in outputs:
                translated_parts.append(
                    MarianEngine._tokenizer.decode(out, skip_special_tokens=True)
                )

        return " ".join(translated_parts)

    async def verify(self, original: str, translation: str) -> str:
        return translation


# ═══════════════════════════════════════════════════════════════
# Motor fabrikası
# ═══════════════════════════════════════════════════════════════

_engine_instance: TranslationEngine | None = None


def get_engine() -> TranslationEngine:
    global _engine_instance
    if _engine_instance is None:
        if TRANSLATION_ENGINE == "ollama":
            logger.info(f"Çeviri motoru: Ollama ({OLLAMA_MODEL})")
            _engine_instance = OllamaEngine()
        elif TRANSLATION_ENGINE == "marian":
            logger.info("Çeviri motoru: MarianMT (Helsinki-NLP/opus-mt-tr-en)")
            _engine_instance = MarianEngine()
        else:
            raise ValueError(f"Bilinmeyen çeviri motoru: {TRANSLATION_ENGINE}")
    return _engine_instance


# ═══════════════════════════════════════════════════════════════
# Üst düzey çeviri fonksiyonları
# ═══════════════════════════════════════════════════════════════

async def translate_pages(
    pages: list[dict],
    verify: bool = True,
    progress_callback=None,
) -> list[dict]:
    """
    Sayfa bazlı çeviri yapar.
    Her chunk ayrı ayrı çevrilir, bağlam penceresi ile tutarlılık sağlanır.
    """
    engine = get_engine()
    translated_pages = []
    context = ""
    total_pages = len(pages)

    for i, page in enumerate(pages):
        if progress_callback:
            await progress_callback(i + 1, total_pages, "page")

        page_text = page["text"] if isinstance(page, dict) else page.text
        page_num = page["page_number"] if isinstance(page, dict) else page.page_number

        if not page_text.strip():
            translated_pages.append({
                "page_number": page_num,
                "original": page_text,
                "translated": "",
            })
            continue

        # Sayfa metnini chunk'lara böl (tablolar bölünmez)
        chunks = split_text_into_chunks(page_text, MAX_CHUNK_CHARS)
        page_translations = []

        for chunk in chunks:
            logger.info(f"Sayfa {page_num} - chunk çeviriliyor ({len(chunk)} karakter)...")
            translation = await engine.translate(chunk, context=context)

            if verify:
                logger.info(f"Sayfa {page_num} - çeviri doğrulanıyor...")
                translation = await engine.verify(chunk, translation)

            # Post-processing: bilinen hataları düzelt
            translation = _post_process(translation)

            page_translations.append(translation)
            context = translation[-300:] if len(translation) > 300 else translation

        translated_text = "\n\n".join(page_translations)
        translated_pages.append({
            "page_number": page_num,
            "original": page_text,
            "translated": translated_text,
        })

    return translated_pages


# ═══════════════════════════════════════════════════════════════
# Post-processing — çeviri sonrası düzeltme
# ═══════════════════════════════════════════════════════════════

_POST_REPLACEMENTS = [
    # Sık yapılan resmi belge çeviri hataları
    (r'\bconsecration\b', 'authentication', re.IGNORECASE),
    (r'\bCONSECRATION\b', 'AUTHENTICATION', 0),
    (r'\bconsecrated\b', 'authenticated', re.IGNORECASE),
    (r'\bthoughts\b', 'remarks', re.IGNORECASE),
    (r'\bTHOUGHTS\b', 'REMARKS', 0),
    (r'\bsex\b', 'gender', re.IGNORECASE),
    (r'\bSEX\b', 'GENDER', 0),
    # Nüfus kayıt terimleri
    (r'\bpopulation sample\b', 'population register extract', re.IGNORECASE),
    (r'\bpopulation record sample\b', 'population register extract', re.IGNORECASE),
    (r'\bPOPULATION RECORD SAMPLE\b', 'POPULATION REGISTER EXTRACT', 0),
    # Yakınlık
    (r'\bhimself\b', 'Self', re.IGNORECASE),
    (r'\bherself\b', 'Self', re.IGNORECASE),
]


def _post_process(text: str) -> str:
    """Bilinen çeviri hatalarını ve artefaktları temizler."""
    # 1. Bağlam prompt sızıntılarını temizle
    text = re.sub(
        r'\[Previous context for translation consistency:.*?\]\s*',
        '', text, flags=re.DOTALL
    )

    # 2. [TABLE_START] / [TABLE_END] marker'larını temizle (LLM bazen bunları kopyalar)
    text = text.replace('[TABLE_START]', '').replace('[TABLE_END]', '')

    # 3. Baştaki ve sondaki --- ayırıcıları temizle
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # Sadece --- olan satırları kaldır (tablo separator değilse)
        if stripped == '---' or stripped == '---\n':
            continue
        cleaned_lines.append(line)
    text = '\n'.join(cleaned_lines)

    # 4. Terminoloji düzeltmeleri
    for pattern, replacement, flags in _POST_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=flags)

    # 5. Çift boş satırları tekile indir
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()
