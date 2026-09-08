import hashlib
import os
import re
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from customs_agent.answering import answer
from customs_agent.analytics import build_analytics
from customs_agent.classifier import classify
from customs_agent.extractors import ExtractionError, chunks, extract_text
from customs_agent.store import Store

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")
UPLOADS = BASE / "data" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
store = Store(BASE / "data" / "customs.db")
answer_cache: dict[str, tuple[float, dict]] = {}
app = FastAPI(title="报关单智能检索助手", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/analytics")
def analytics_page():
    return FileResponse(BASE / "static" / "analytics.html")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_enabled": bool(os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")),
        "llm_model": os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL"),
        "llm_mode": os.getenv("LLM_API_MODE", "responses"),
    }


@app.get("/api/documents")
def documents():
    return store.list_documents()


@app.get("/api/analytics")
def analytics():
    return build_analytics(store.list_documents())


@app.post("/api/upload")
def upload(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".docx", ".txt", ".md"}:
        raise HTTPException(415, "仅支持 PDF、DOCX、TXT 和 Markdown 文件")
    safe_stem = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", Path(file.filename or "file").stem)[:80]
    target = UPLOADS / f"{uuid4().hex}_{safe_stem}{suffix}"
    max_bytes = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024
    digest = hashlib.sha256()
    size = 0
    with target.open("wb") as output:
        while block := file.file.read(1024 * 1024):
            size += len(block)
            if size > max_bytes:
                output.close()
                target.unlink(missing_ok=True)
                raise HTTPException(413, "文件超过上传大小限制")
            digest.update(block)
            output.write(block)
    sha = digest.hexdigest()
    existing = store.by_hash(sha)
    if existing:
        target.unlink(missing_ok=True)
        existing_path = UPLOADS / existing["stored_name"]
        try:
            text, pages = extract_text(existing_path)
            fields = classify(text)
            values = chunks(text)
            store.reindex(existing["id"], pages, fields, values)
            answer_cache.clear()
        except ExtractionError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "status": "reindexed", "document_id": existing["id"],
            "chunks": len(values), "fields": fields,
        }
    try:
        text, pages = extract_text(target)
        fields = classify(text)
        values = chunks(text)
        doc_id = store.add(file.filename or target.name, target.name, sha, pages, fields, values)
        answer_cache.clear()
    except ExtractionError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {"status": "indexed", "document_id": doc_id, "chunks": len(values), "fields": fields}


@app.post("/api/ask")
def ask(payload: Question):
    if any(phrase in payload.question for phrase in ("全部数据", "所有数据", "完整数据", "全部字段", "所有字段")):
        documents = store.list_documents()
        if not documents:
            return {"answer": "未在已入库的报关单中找到相关信息。", "mode": "structured-none", "sources": []}
        if len(documents) > 1:
            return {
                "answer": "知识库中有多份报关单，请在问题中提供海关编号、企业名称或文件名以确定查询范围。",
                "mode": "needs-scope", "sources": [],
            }
        document = documents[0]
        response_text = "\n".join(f"{key}：{value}" for key, value in document["fields"].items())
        return {
            "answer": response_text, "mode": "structured-all",
            "sources": [{
                "document_id": document["id"], "filename": document["filename"],
                "chunk_index": -1, "excerpt": f"已识别 {len(document['fields'])} 个字段",
            }],
        }
    field_name, matches = store.find_structured_field(payload.question)
    if field_name:
        if not matches:
            return {
                "answer": "未在已入库的报关单中找到相关信息。",
                "mode": "structured-none", "sources": [],
            }
        unique_values = list(dict.fromkeys(item["value"] for item in matches))
        if len(unique_values) == 1:
            response_text = unique_values[0]
        else:
            response_text = "\n".join(f"{item['filename']}：{item['value']}" for item in matches)
        return {
            "answer": response_text, "mode": "structured",
            "sources": [{
                "document_id": item["document_id"], "filename": item["filename"],
                "chunk_index": -1, "excerpt": f"{item['field']}：{item['value']}",
            } for item in matches],
        }
    cache_key = re.sub(r"\s+", "", payload.question).lower()
    cached = answer_cache.get(cache_key)
    if cached and cached[0] > time.time():
        return {**cached[1], "cached": True}
    evidence = store.search(payload.question, limit=4)
    text, mode = answer(payload.question, evidence)
    sources = [{
        "document_id": item["document_id"], "filename": item["filename"],
        "chunk_index": item["chunk_index"], "excerpt": item["content"][:600]
    } for item in evidence]
    result = {"answer": text, "mode": mode, "sources": sources}
    if len(answer_cache) >= 200:
        answer_cache.clear()
    answer_cache[cache_key] = (time.time() + 300, result)
    return result
