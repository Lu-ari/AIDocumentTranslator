"""
FastAPI ana uygulama.
PDF yükleme, çeviri ve indirme endpoint'leri.
WebSocket ile gerçek zamanlı ilerleme takibi.
"""

import uuid
import asyncio
import logging
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import UPLOAD_DIR, OUTPUT_DIR, MAX_FILE_SIZE_MB, ALLOWED_EXTENSIONS
from app.pdf_processor import extract_text_from_pdf
from app.translator import translate_pages
from app.pdf_builder import build_translated_pdf, build_bilingual_pdf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Document Translator",
    description="Türkçe PDF dokümanlarını yüksek doğrulukla İngilizceye çeviren AI destekli web uygulaması",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Statik dosyalar
STATIC_DIR = Path(__file__).parent.parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Aktif çeviri görevleri
active_tasks: dict[str, dict] = {}

# WebSocket bağlantıları
ws_connections: dict[str, WebSocket] = {}


@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return HTMLResponse("<h1>AI Document Translator</h1><p>static/index.html bulunamadı</p>")


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """PDF dosyası yükler ve çeviri görevini başlatır."""
    # Dosya uzantısı kontrolü
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Desteklenmeyen dosya formatı: {file_ext}. Sadece PDF kabul edilir.")

    # Dosya boyutu kontrolü
    content = await file.read()
    file_size_mb = len(content) / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(400, f"Dosya çok büyük: {file_size_mb:.1f}MB. Maksimum: {MAX_FILE_SIZE_MB}MB")

    # Dosyayı kaydet
    task_id = str(uuid.uuid4())
    upload_path = UPLOAD_DIR / f"{task_id}{file_ext}"
    upload_path.write_bytes(content)

    # Görev kaydı oluştur
    active_tasks[task_id] = {
        "status": "uploaded",
        "filename": file.filename,
        "upload_path": str(upload_path),
        "progress": 0,
        "total_pages": 0,
        "current_page": 0,
        "error": None,
    }

    return {
        "task_id": task_id,
        "filename": file.filename,
        "file_size_mb": round(file_size_mb, 2),
        "message": "Dosya yüklendi. Çeviriyi başlatmak için /api/translate/{task_id} endpoint'ini kullanın.",
    }


@app.post("/api/translate/{task_id}")
async def start_translation(task_id: str, verify: bool = True, bilingual: bool = False):
    """Yüklenen PDF için çeviri sürecini başlatır."""
    if task_id not in active_tasks:
        raise HTTPException(404, "Görev bulunamadı")

    task = active_tasks[task_id]
    if task["status"] not in ("uploaded", "error"):
        raise HTTPException(400, f"Görev zaten çalışıyor veya tamamlandı: {task['status']}")

    task["status"] = "processing"
    task["verify"] = verify
    task["bilingual"] = bilingual

    # Arka planda çeviri başlat
    asyncio.create_task(_run_translation(task_id))

    return {
        "task_id": task_id,
        "status": "processing",
        "message": "Çeviri başlatıldı. İlerlemeyi /api/status/{task_id} ile takip edebilirsiniz.",
    }


@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    """Çeviri görevinin durumunu döndürür."""
    if task_id not in active_tasks:
        raise HTTPException(404, "Görev bulunamadı")

    task = active_tasks[task_id]
    return {
        "task_id": task_id,
        "status": task["status"],
        "filename": task["filename"],
        "progress": task["progress"],
        "total_pages": task["total_pages"],
        "current_page": task["current_page"],
        "error": task["error"],
    }


@app.get("/api/download/{task_id}")
async def download_translated(task_id: str):
    """Çevrilmiş PDF'i indirir."""
    if task_id not in active_tasks:
        raise HTTPException(404, "Görev bulunamadı")

    task = active_tasks[task_id]
    if task["status"] != "completed":
        raise HTTPException(400, f"Çeviri henüz tamamlanmadı: {task['status']}")

    output_path = Path(task["output_path"])
    if not output_path.exists():
        raise HTTPException(500, "Çeviri dosyası bulunamadı")

    download_name = f"translated_{task['filename']}"
    return FileResponse(
        str(output_path),
        media_type="application/pdf",
        filename=download_name,
    )


@app.websocket("/ws/{task_id}")
async def websocket_progress(websocket: WebSocket, task_id: str):
    """WebSocket ile gerçek zamanlı ilerleme güncellemesi."""
    await websocket.accept()
    ws_connections[task_id] = websocket

    try:
        while True:
            # Heartbeat
            await asyncio.sleep(1)
            if task_id in active_tasks:
                task = active_tasks[task_id]
                await websocket.send_json({
                    "status": task["status"],
                    "progress": task["progress"],
                    "total_pages": task["total_pages"],
                    "current_page": task["current_page"],
                    "error": task["error"],
                })
                if task["status"] in ("completed", "error"):
                    break
    except WebSocketDisconnect:
        pass
    finally:
        ws_connections.pop(task_id, None)


async def _run_translation(task_id: str):
    """Arka planda çeviri işlemini yürütür."""
    task = active_tasks[task_id]

    try:
        # 1. PDF'den metin çıkar
        task["status"] = "extracting"
        logger.info(f"[{task_id}] PDF metin çıkarma başladı: {task['filename']}")

        pdf_content = extract_text_from_pdf(task["upload_path"])
        task["total_pages"] = pdf_content.total_pages

        # Çevrilecek sayfa verilerini hazırla
        pages_data = [
            {"page_number": p.page_number, "text": p.text}
            for p in pdf_content.pages
        ]

        # 2. Çeviri
        task["status"] = "translating"
        logger.info(f"[{task_id}] Çeviri başladı: {pdf_content.total_pages} sayfa")

        async def progress_cb(current, total, unit="page"):
            task["current_page"] = current
            task["progress"] = int((current / total) * 100)

        translated_pages = await translate_pages(
            pages_data,
            verify=task.get("verify", True),
            progress_callback=progress_cb,
        )

        # 3. PDF oluştur
        task["status"] = "building_pdf"
        logger.info(f"[{task_id}] PDF oluşturuluyor")

        output_filename = f"{task_id}_translated.pdf"
        output_path = OUTPUT_DIR / output_filename

        if task.get("bilingual", False):
            build_bilingual_pdf(translated_pages, output_path)
        else:
            build_translated_pdf(translated_pages, output_path, task["filename"])

        task["output_path"] = str(output_path)
        task["status"] = "completed"
        task["progress"] = 100
        logger.info(f"[{task_id}] Çeviri tamamlandı!")

    except Exception as e:
        logger.error(f"[{task_id}] Çeviri hatası: {e}", exc_info=True)
        task["status"] = "error"
        task["error"] = str(e)
