"""FastAPI 路由。create_app 可注入 run／check，測試不碰真 AI。"""
import threading
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import ai_runner, ai_tasks, pdf_service
from .schema import Note, flatten
from .storage import NotFound, Storage

DEFAULT_DATA = Path(__file__).resolve().parents[2] / "papers"
MAX_PDF_BYTES = 50 * 1024 * 1024


class EditRequest(BaseModel):
    engine: ai_runner.Engine = "claude"
    message: str = Field(min_length=1)
    block_ids: list[str] = Field(min_length=1)
    selected_text: str = ""


class RestoreRequest(BaseModel):
    snapshot: str


def create_app(data_dir: Path, run=ai_runner.run, check=ai_runner.check_engine) -> FastAPI:
    storage = Storage(data_dir)
    app = FastAPI(title="Paper Notes")
    app.state.run_override = None  # 測試可替換 AI 呼叫
    jobs: dict[str, dict] = {}
    busy: set[str] = set()
    lock = threading.Lock()

    def ai_run(*args, **kwargs):
        return (app.state.run_override or run)(*args, **kwargs)

    def not_found(e: NotFound):
        return HTTPException(404, f"找不到：{e}")

    @app.get("/api/health")
    def health():
        return {engine: check(engine) for engine in ("claude", "codex")}

    @app.get("/api/papers")
    def list_papers():
        return [asdict(p) for p in storage.list_papers()]

    @app.post("/api/papers")
    async def upload(file: UploadFile = File(...), title: str = Form(""),
                     engine: ai_runner.Engine = Form("claude")):
        data = await file.read()
        if not data.startswith(b"%PDF"):
            raise HTTPException(400, "檔案不是 PDF")
        if len(data) > MAX_PDF_BYTES:
            raise HTTPException(413, "PDF 超過 50MB")
        slug = storage.create_paper(title.strip() or Path(file.filename or "paper").stem, data)
        job_id = uuid.uuid4().hex
        jobs[job_id] = {"status": "running", "step": "擷取圖片", "error": None, "slug": slug}
        threading.Thread(target=import_job, args=(job_id, slug, engine), daemon=True).start()
        return {"slug": slug, "job_id": job_id}

    def import_job(job_id: str, slug: str, engine: str):
        job = jobs[job_id]
        try:
            d = storage.paper_dir(slug)
            figures = pdf_service.extract_figures(d / "paper.pdf", d / "figures")
            job["step"] = "產生摘要"
            summary = ai_tasks.generate_summary(engine, d, run=ai_run)
            storage.write_summary(slug, summary)
            job["step"] = "產生筆記"
            blocks = ai_tasks.generate_note(engine, d, summary, figures, run=ai_run)
            storage.write_note(slug, Note(blocks=blocks))
            job.update(status="done", step="完成")
        except Exception as e:  # 任何錯誤都要讓 job 結束，不能卡在 running
            job.update(status="error", error=str(e))

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        if job_id not in jobs:
            raise HTTPException(404, "找不到這個工作")
        return jobs[job_id]

    @app.get("/api/papers/{slug}/note")
    def get_note(slug: str):
        try:
            return storage.read_note(slug).model_dump(exclude_none=True)
        except NotFound as e:
            raise not_found(e)

    @app.put("/api/papers/{slug}/note")
    def put_note(slug: str, note: Note):
        try:
            storage.write_note(slug, note)
        except NotFound as e:
            raise not_found(e)
        return {"ok": True}

    @app.get("/api/papers/{slug}/figures")
    def list_figures(slug: str):
        try:
            return sorted(p.name for p in storage.figures_dir(slug).glob("*.png"))
        except NotFound as e:
            raise not_found(e)

    @app.get("/api/papers/{slug}/figures/{name}")
    def get_figure(slug: str, name: str):
        try:
            return FileResponse(storage.figure_path(slug, name), media_type="image/png")
        except NotFound as e:
            raise not_found(e)

    @app.get("/api/papers/{slug}/chat")
    def get_chat(slug: str):
        try:
            return storage.read_chat(slug)
        except NotFound as e:
            raise not_found(e)

    @app.post("/api/papers/{slug}/edit")
    def edit(slug: str, req: EditRequest):
        with lock:
            if slug in busy:
                raise HTTPException(409, "這篇筆記已有一個 AI 修改進行中，請稍候")
            busy.add(slug)
        try:
            return _edit(slug, req)
        except NotFound as e:
            raise not_found(e)
        finally:
            with lock:
                busy.discard(slug)

    def _edit(slug: str, req: EditRequest):
        note = storage.read_note(slug)
        flat = flatten(note.blocks)
        ids = [b.id for b in flat]
        missing = [i for i in req.block_ids if i not in ids]
        if missing:
            raise HTTPException(400, f"找不到區塊：{missing}")
        idx = sorted(ids.index(i) for i in req.block_ids)
        selected = [flat[i] for i in idx]
        before = flat[idx[0] - 1] if idx[0] > 0 else None
        after = flat[idx[-1] + 1] if idx[-1] + 1 < len(flat) else None
        in_columns = {leaf.id for b in note.blocks if b.type == "columns"
                      for col in b.columns for leaf in col.blocks}
        d = storage.paper_dir(slug)
        dump = lambda b: b.model_dump(exclude_none=True) if b is not None else None
        storage.append_chat(slug, {"role": "user", "text": req.message, "engine": req.engine,
                                   "block_ids": req.block_ids, "selected_text": req.selected_text})
        try:
            result = ai_tasks.edit_selection(
                req.engine, d, storage.read_summary(slug), [dump(b) for b in selected],
                req.selected_text, dump(before), dump(after), req.message,
                sorted(p.name for p in (d / "figures").glob("*.png")),
                allow_columns=not any(i in in_columns for i in req.block_ids), run=ai_run)
        except ai_runner.AIError as e:
            raw = getattr(e, "raw", None)
            storage.append_chat(slug, {"role": "error", "text": str(e), "raw": raw})
            raise HTTPException(502, {"message": str(e), "raw": raw})
        snapshot = storage.snapshot(slug) if result.replace is not None else None
        replace = [dump(b) for b in result.replace] if result.replace is not None else None
        storage.append_chat(slug, {"role": "assistant", "text": result.reply, "engine": req.engine,
                                   "snapshot": snapshot})
        return {"reply": result.reply, "replace": replace, "snapshot": snapshot}

    @app.post("/api/papers/{slug}/restore")
    def restore(slug: str, req: RestoreRequest):
        try:
            return storage.restore(slug, req.snapshot).model_dump(exclude_none=True)
        except NotFound as e:
            raise not_found(e)

    return app
