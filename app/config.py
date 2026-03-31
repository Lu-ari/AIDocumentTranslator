import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Çeviri motoru seçimi ──────────────────────────────────────
# "ollama"  → Yerel LLM (Ollama kurulu olmalı, ÜCRETSİZ, en iyi kalite)
# "marian"  → HuggingFace MarianMT (pip install yeterli, ÜCRETSİZ, kurulumu kolay)
TRANSLATION_ENGINE = os.getenv("TRANSLATION_ENGINE", "ollama")

# ── Ollama ayarları ───────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3")

# ── MarianMT ayarları ────────────────────────────────────────
MARIAN_MODEL_NAME = "Helsinki-NLP/opus-mt-tr-en"

# ── Genel ayarlar ────────────────────────────────────────────
# Chunk boyutu (karakter) - büyük PDF'ler parçalanır
MAX_CHUNK_CHARS = 3000

# Maksimum dosya boyutu (MB)
MAX_FILE_SIZE_MB = 50

# Desteklenen dosya uzantıları
ALLOWED_EXTENSIONS = {".pdf"}
