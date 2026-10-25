import os
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import classify, mock_authority, ocr, pipeline
from .api import router as api_router
from .db import Base, SessionLocal, engine
from .models import Institution
from .seed import seed

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="PRAMAAN - AI-Powered Application Validation, Document Authentication & Compliance Verification (SIH26261 prototype)", version="0.1.0",
              description="Prototype for SIH 2026 PS 26261. Synthetic documents only. Every output is decision support with evidence; forgery indicators are preliminary and human-verified.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router)
app.include_router(mock_authority.router)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    classify.train()
    mock_authority.load()
    db = SessionLocal()
    try:
        pipeline.load_checklists(db)
        if not db.query(Institution).count():
            print("PRAMAAN: first start - warming up OCR engine and generating the synthetic corpus (1-2 minutes)...")
            ocr.warmup()
            seed(db)
            print("PRAMAAN: seed complete")
        else:
            threading.Thread(target=ocr.warmup, daemon=True).start()
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"ok": True, "service": "pramaan", "ocr": ocr.status()}


app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/")
@app.get("/app/{rest:path}")
def index(rest: str = None):
    return FileResponse(str(FRONTEND / "index.html"))
