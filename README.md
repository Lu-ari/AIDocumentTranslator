# AI Document Translator

> Türkçe PDF belgelerini yüksek doğrulukla İngilizceye çeviren, tamamen **ücretsiz** ve yerel çalışan web uygulaması. API key gerekmez.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-orange)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

---

## Özellikler

| Özellik | Detay |
|---|---|
| **Yerel AI** | Ollama (qwen2.5, gemma3 vb.) — internet bağlantısı gerekmez |
| **Tablo koruması** | PDF tablolar algılanır, landscape modda düzgün render edilir |
| **Resmi belge sözlüğü** | 40+ hukuki/resmî terim zorunlu olarak doğru çevrilir |
| **Çift geçişli doğrulama** | Çeviri sonrası ayrı LLM review'u ile kalite kontrolü |
| **Bağlam tutarlılığı** | Chunk'lar arası bağlam penceresi ile tutarlı terminoloji |
| **Gerçek zamanlı ilerleme** | WebSocket ile anlık sayfa/ilerleme takibi |
| **İki dilli çıktı** | Opsiyonel TR + EN yan yana PDF |
| **Drag & Drop UI** | Sürükle-bırak, sıfır kurulum gerektiren web arayüzü |

---

## Demo

| Orijinal (TR) | Çeviri (EN) |
|---|---|
| Nüfus Kayıt Örneği | Population Register Extract |
| Tasdik | Authentication |
| Yakınlık Derecesi | Relationship (Kinship) |
| Olaylar ve Tarihleri | Events and Dates |

---

## Kurulum

### Gereksinimler

- Python 3.11+
- [Ollama](https://ollama.com/download) kurulu

### Hızlı Başlangıç

```bash
# 1. Repoyu klonla
git clone https://github.com/Lu-ari/AIDocumentTranslator.git
cd AIDocumentTranslator

# 2. LLM modelini indir (bir kere yapılır)
ollama pull qwen2.5:14b        # En iyi kalite (~9GB)
# veya
ollama pull gemma3             # Daha hafif (~5GB)

# 3. Python bağımlılıklarını yükle
pip install -r requirements.txt

# 4. .env dosyasını yapılandır
cp .env.example .env
# .env içinde OLLAMA_MODEL=qwen2.5:14b satırını kullandığın modelle değiştir

# 5. Uygulamayı başlat
python run.py
```

Tarayıcıda `http://localhost:8000` adresine git.

### Alternatif: MarianMT (Ollama kurmak istemeyenler için)

```bash
# .env dosyasında:
TRANSLATION_ENGINE=marian

# İlk çalıştırmada ~300MB model otomatik indirilir
python run.py
```

---

## Kullanım

1. PDF dosyasını sürükle-bırak veya tıklayarak yükle (max 50MB)
2. Opsiyonları seç:
   - **Çift kontrol doğrulama** — kalite için önerilir
   - **İki dilli çıktı** — orijinal + çeviri yan yana
3. "Çeviriyi Başlat" butonuna tıkla
4. Gerçek zamanlı ilerlemeyi takip et
5. Tamamlandığında PDF'i indir

---

## Motor Karşılaştırması

| | Ollama (qwen2.5:14b) | Ollama (gemma3) | MarianMT |
|---|---|---|---|
| **Kalite** | En iyi | Çok iyi | İyi |
| **Hız** | Orta | Orta | Hızlı |
| **Tablo anlama** | Mükemmel | İyi | Yok |
| **Çift doğrulama** | Var | Var | Yok |
| **API key** | Gerekmez | Gerekmez | Gerekmez |
| **Boyut** | ~9GB | ~5GB | ~300MB |

---

## Mimari

```
AIDocumentTranslator/
├── app/
│   ├── config.py          # Env bazlı yapılandırma
│   ├── main.py            # FastAPI + WebSocket endpoint'leri
│   ├── pdf_processor.py   # PyMuPDF ile tablo+metin çıkarma
│   ├── pdf_builder.py     # FPDF2 ile PDF render (landscape, word-wrap)
│   └── translator.py      # Ollama / MarianMT çeviri motoru
├── static/
│   └── index.html         # Drag & Drop web arayüzü
├── uploads/               # Yüklenen PDF'ler (otomatik)
├── outputs/               # Çevrilmiş PDF'ler (otomatik)
├── .env.example
├── requirements.txt
└── run.py
```

---

## Çeviri Pipeline'ı

```
PDF Dosyası
    │
    ▼
PyMuPDF → Metin + Tablo çıkarma (tablo konum tespiti)
    │
    ▼
Sahte tablo filtresi (sayfa numarası barları, URL'ler elenir)
    │
    ▼
Chunk bölme (paragraf sınırları korunur, tablolar bölünmez)
    │
    ▼
Ollama LLM → Çeviri (glossary zorunlu, temperature=0.05)
    │
    ▼
Doğrulama LLM → Kalite review (VERIFIED veya düzeltilmiş çeviri)
    │
    ▼
Post-processing → Terminoloji düzeltme, artefakt temizleme
    │
    ▼
FPDF2 → PDF render (landscape modu, tablo render, word-wrap)
```

---

## API Referansı

| Endpoint | Method | Açıklama |
|---|---|---|
| `/` | GET | Web arayüzü |
| `/api/upload` | POST | PDF yükle → `task_id` döner |
| `/api/translate/{task_id}` | POST | Çeviriyi başlat |
| `/api/status/{task_id}` | GET | Anlık durum sorgula |
| `/api/download/{task_id}` | GET | Çevrilmiş PDF indir |
| `/ws/{task_id}` | WebSocket | Gerçek zamanlı ilerleme |

---

## Konfigürasyon (.env)

```env
# Çeviri motoru: "ollama" veya "marian"
TRANSLATION_ENGINE=ollama

# Ollama ayarları
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:14b
```

---

## Teknoloji Yığını

- **Backend**: FastAPI, Uvicorn, Python 3.11
- **PDF İşleme**: PyMuPDF (fitz), FPDF2
- **LLM**: Ollama (yerel), HuggingFace Transformers (MarianMT)
- **İletişim**: WebSocket (async), httpx
- **Frontend**: Vanilla HTML/CSS/JS (sıfır bağımlılık)
