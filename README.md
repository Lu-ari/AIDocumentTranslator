# AI Document Translator — Türkçe → İngilizce (Ücretsiz)

Tamamen **ücretsiz**, yerel AI modelleriyle Türkçe PDF dokümanlarını İngilizceye çeviren web uygulaması. API key gerekmez.

## Özellikler

- **İki motor seçeneği**:
  - **Ollama** (önerilen): Yerel LLM (gemma3, llama3.1 vb.) — en iyi kalite, ücretsiz
  - **MarianMT**: HuggingFace Helsinki-NLP/opus-mt-tr-en — sadece pip install yeterli
- **Çift geçişli doğrulama** (Ollama modunda): İlk çeviriden sonra otomatik kalite kontrolü
- **Bağlam-duyarlı çeviri**: Chunk'lar arası tutarlılığı korur
- **Gerçek zamanlı ilerleme**: WebSocket ile anlık ilerleme takibi
- **İki dilli çıktı**: Opsiyonel olarak orijinal + çeviri yan yana PDF
- **Yapısal metin çıkarma**: Paragraf, başlık yapısını korur
- **Drag & Drop arayüz**: Modern, kullanımı kolay web arayüzü

## Kurulum

### Seçenek A: Ollama ile (Önerilen — En İyi Kalite)

```bash
# 1. Ollama'yı indir ve kur: https://ollama.com/download
# 2. Model indir (bir kere yapılır, ~5GB)
ollama pull gemma3

# 3. Python paketlerini yükle
pip install -r requirements.txt

# 4. Uygulamayı başlat
python run.py
```

### Seçenek B: MarianMT ile (Sıfır Kurulum)

```bash
# 1. Python paketlerini yükle
pip install -r requirements.txt

# 2. .env dosyasını düzenle
#    TRANSLATION_ENGINE=marian olarak değiştir

# 3. Uygulamayı başlat (ilk çalıştırmada model otomatik indirilir ~300MB)
python run.py
```

## Kullanım

1. Tarayıcıda `http://localhost:8000` adresine git
2. Türkçe PDF dokümanını sürükle-bırak veya tıklayarak yükle
3. Opsiyonları seç:
   - **Çift kontrol doğrulama**: Çeviri sonrası otomatik doğrulama (Ollama modunda)
   - **İki dilli çıktı**: TR + EN yan yana PDF
4. "Çeviriyi Başlat" butonuna tıkla
5. Çeviri tamamlandığında PDF'i indir

## Motor Karşılaştırması

| Özellik | Ollama (gemma3) | MarianMT |
|---|---|---|
| Kalite | ⭐⭐⭐⭐⭐ En iyi | ⭐⭐⭐ İyi |
| Hız | Orta (GPU ile hızlı) | Hızlı |
| Kurulum | Ollama + model indir | Sadece pip install |
| Bağlam anlama | Evet | Sınırlı |
| Çift doğrulama | Evet | Hayır |
| API key | Gerekmez | Gerekmez |
| Fiyat | Ücretsiz | Ücretsiz |

## Mimari

```
AiDocTranslater/
├── app/
│   ├── config.py          # Yapılandırma ayarları
│   ├── main.py            # FastAPI uygulama & route'lar
│   ├── pdf_processor.py   # PDF metin çıkarma (PyMuPDF)
│   ├── pdf_builder.py     # Çevrilmiş PDF oluşturma (FPDF2)
│   └── translator.py      # LLM çeviri motoru (GPT-4o)
├── static/
│   └── index.html         # Web arayüzü
├── uploads/               # Yüklenen PDF'ler (otomatik oluşur)
├── outputs/               # Çevrilmiş PDF'ler (otomatik oluşur)
├── requirements.txt
├── run.py
└── .env.example
```

## Çeviri Stratejisi

### Ollama modu
1. Yerel LLM ile bağlam-duyarlı çeviri (system prompt + önceki chunk bağlamı)
2. Düşük sıcaklık (temperature=0.1) ile tutarlı çıktı
3. Çift geçişli doğrulama: ayrı bir review prompt ile kalite kontrolü
4. Retry mekanizması: hata durumunda üstel geri çekilme

### MarianMT modu
1. Helsinki-NLP/opus-mt-tr-en — Türkçe→İngilizce için eğitilmiş uzman model
2. Cümle bazlı batch çeviri (performans optimizasyonu)
3. Beam search (num_beams=4) ile en iyi çeviri seçimi

## API Endpoint'leri

| Endpoint | Method | Açıklama |
|---|---|---|
| `/` | GET | Web arayüzü |
| `/api/upload` | POST | PDF yükle |
| `/api/translate/{task_id}` | POST | Çeviri başlat |
| `/api/status/{task_id}` | GET | Durum sorgula |
| `/api/download/{task_id}` | GET | Çevrilmiş PDF indir |
| `/ws/{task_id}` | WS | Gerçek zamanlı ilerleme |

## Gereksinimler

- Python 3.11+
- **Ollama modu**: [Ollama](https://ollama.com/download) kurulu + model indirilmiş
- **MarianMT modu**: Sadece pip install (ilk çalıştırmada ~300MB model indirilir)
