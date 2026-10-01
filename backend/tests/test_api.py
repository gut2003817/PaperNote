import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRun
from make_sample_pdf import make_sample_pdf
from paper_notes.api import create_app

BAR = {"mark": "bar", "data": {"values": [{"x": "A", "y": 1}]}}
SUMMARY = {"summary_md": "# 摘要\n" + "重點。" * 30}
NOTE_BLOCKS = [
    {"type": "heading", "level": 1, "text": "Sample"},
    {"type": "paragraph", "text": "原始段落"},
    {"type": "chart", "spec": BAR, "source": "Table 1, p.1"},
]


def blocks_out(blocks, reply="ok"):
    return {"reply": reply, "blocks_json": json.dumps(blocks, ensure_ascii=False)}


@pytest.fixture
def pdf_bytes(tmp_path):
    return make_sample_pdf(tmp_path / "s.pdf").read_bytes()


def make_client(tmp_path, outputs):
    run = FakeRun(outputs)
    check = lambda engine: {"ok": True, "detail": f"{engine} ok"}
    return TestClient(create_app(tmp_path / "data", run=run, check=check)), run


def wait_job(client, job_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job 未在時限內結束")


def imported(tmp_path, pdf_bytes, extra_outputs=()):
    client, run = make_client(tmp_path, [SUMMARY, blocks_out(NOTE_BLOCKS), *extra_outputs])
    res = client.post("/api/papers", files={"file": ("s.pdf", pdf_bytes, "application/pdf")},
                      data={"title": "Sample", "engine": "claude"})
    assert res.status_code == 200
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "done", job
    return client, run, res.json()["slug"]


def test_health(tmp_path):
    client, _ = make_client(tmp_path, [])
    assert client.get("/api/health").json() == {
        "claude": {"ok": True, "detail": "claude ok"}, "codex": {"ok": True, "detail": "codex ok"}}


def test_upload_rejects_non_pdf(tmp_path):
    client, _ = make_client(tmp_path, [])
    res = client.post("/api/papers", files={"file": ("a.txt", b"hello", "text/plain")})
    assert res.status_code == 400 and "PDF" in res.json()["detail"]


def test_import_flow(tmp_path, pdf_bytes):
    client, run, slug = imported(tmp_path, pdf_bytes)
    note = client.get(f"/api/papers/{slug}/note").json()
    assert [b["type"] for b in note["blocks"]] == ["heading", "paragraph", "chart"]
    assert note["blocks"][2]["verified"] is False
    figures = client.get(f"/api/papers/{slug}/figures").json()
    assert "p1-1.png" in figures and "page-2.png" in figures
    img = client.get(f"/api/papers/{slug}/figures/page-1.png")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert client.get("/api/papers").json()[0]["has_note"] is True
    assert "page-1.png" in run.prompts[1]


def test_import_ai_error_marks_job_error(tmp_path, pdf_bytes):
    from paper_notes.ai_runner import AIError
    client, _ = make_client(tmp_path, [AIError("claude 未登入")])
    res = client.post("/api/papers", files={"file": ("s.pdf", pdf_bytes, "application/pdf")})
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "error" and "未登入" in job["error"]


def test_import_corrupt_pdf_marks_job_error(tmp_path):
    client, _ = make_client(tmp_path, [])
    res = client.post("/api/papers", files={"file": ("b.pdf", b"%PDF-1.4 garbage", "application/pdf")})
    job = wait_job(client, res.json()["job_id"])
    assert job["status"] == "error" and "PDF" in job["error"]


def test_note_get_put(tmp_path, pdf_bytes):
    client, _, slug = imported(tmp_path, pdf_bytes)
    note = client.get(f"/api/papers/{slug}/note").json()
    note["blocks"][1]["text"] = "手動修改"
    assert client.put(f"/api/papers/{slug}/note", json=note).json() == {"ok": True}
    assert client.get(f"/api/papers/{slug}/note").json()["blocks"][1]["text"] == "手動修改"
    bad = {"blocks": [{"type": "chart", "spec": {}, "source": ""}]}
    assert client.put(f"/api/papers/{slug}/note", json=bad).status_code == 422


def test_unknown_slug_and_bad_figure_404(tmp_path, pdf_bytes):
    client, _, slug = imported(tmp_path, pdf_bytes)
    assert client.get("/api/papers/nope-000000/note").status_code == 404
    assert client.get(f"/api/papers/{slug}/figures/..%2Fpaper.pdf").status_code == 404


def test_edit_replace_creates_snapshot_and_chat(tmp_path, pdf_bytes):
    client, run, slug = imported(tmp_path, pdf_bytes,
                                 [blocks_out([{"type": "paragraph", "text": "新段落"}], reply="已改寫")])
    before = client.get(f"/api/papers/{slug}/note").json()
    pid = before["blocks"][1]["id"]
    res = client.post(f"/api/papers/{slug}/edit", json={
        "engine": "claude", "message": "改白話", "block_ids": [pid], "selected_text": "原始"})
    assert res.status_code == 200
    body = res.json()
    assert body["reply"] == "已改寫" and body["replace"][0]["text"] == "新段落"
    assert body["snapshot"]
    assert client.get(f"/api/papers/{slug}/note").json() == before, "edit 端點不可寫 note.json"
    assert "Sample" in run.prompts[2], "前一個區塊應作為上下文"
    roles = [c["role"] for c in client.get(f"/api/papers/{slug}/chat").json()]
    assert roles == ["user", "assistant"]


def test_edit_reply_only_has_no_snapshot(tmp_path, pdf_bytes):
    client, _, slug = imported(tmp_path, pdf_bytes, [{"reply": "這段在說…", "blocks_json": ""}])
    pid = client.get(f"/api/papers/{slug}/note").json()["blocks"][1]["id"]
    body = client.post(f"/api/papers/{slug}/edit",
                       json={"message": "這是什麼意思？", "block_ids": [pid]}).json()
    assert body == {"reply": "這段在說…", "replace": None, "snapshot": None}


def test_edit_format_error_returns_502_and_logs(tmp_path, pdf_bytes):
    bad = {"reply": "x", "blocks_json": "[{]"}
    client, _, slug = imported(tmp_path, pdf_bytes, [bad, bad])
    before = client.get(f"/api/papers/{slug}/note").json()
    pid = before["blocks"][1]["id"]
    res = client.post(f"/api/papers/{slug}/edit", json={"message": "改", "block_ids": [pid]})
    assert res.status_code == 502
    assert "格式錯誤" in res.json()["detail"]["message"] and "[{]" in res.json()["detail"]["raw"]
    assert client.get(f"/api/papers/{slug}/note").json() == before
    assert client.get(f"/api/papers/{slug}/chat").json()[-1]["role"] == "error"


def test_edit_unknown_block_400(tmp_path, pdf_bytes):
    client, _, slug = imported(tmp_path, pdf_bytes)
    res = client.post(f"/api/papers/{slug}/edit", json={"message": "改", "block_ids": ["nope"]})
    assert res.status_code == 400


def test_edit_inside_columns_disallows_columns(tmp_path, pdf_bytes):
    cols = {"type": "columns", "columns": [
        {"widthPct": 50, "blocks": [{"type": "paragraph", "text": "a"}]},
        {"widthPct": 50, "blocks": [{"type": "paragraph", "text": "b"}]}]}
    client, run, slug = imported(tmp_path, pdf_bytes,
                                 [blocks_out([cols]), blocks_out([{"type": "paragraph", "text": "ok"}])])
    note = client.get(f"/api/papers/{slug}/note").json()
    note["blocks"].append({"id": "cc", "type": "columns", "columns": [
        {"widthPct": 50, "blocks": [{"id": "left", "type": "paragraph", "text": "L"}]},
        {"widthPct": 50, "blocks": [{"id": "right", "type": "paragraph", "text": "R"}]}]})
    client.put(f"/api/papers/{slug}/note", json=note)
    body = client.post(f"/api/papers/{slug}/edit", json={"message": "改", "block_ids": ["left"]}).json()
    assert body["replace"][0]["type"] == "paragraph"
    assert "並排欄位內" in run.prompts[2]


def test_concurrent_edit_returns_409(tmp_path, pdf_bytes):
    gate = threading.Event()
    entered = threading.Event()
    client, run, slug = imported(tmp_path, pdf_bytes)

    def slow(*args, **kwargs):
        entered.set()
        gate.wait(5)
        return {"reply": "慢", "blocks_json": ""}

    client.app.state.run_override = slow
    pid = client.get(f"/api/papers/{slug}/note").json()["blocks"][1]["id"]
    results = {}
    t = threading.Thread(target=lambda: results.update(
        first=client.post(f"/api/papers/{slug}/edit", json={"message": "a", "block_ids": [pid]})))
    t.start()
    assert entered.wait(5)
    second = client.post(f"/api/papers/{slug}/edit", json={"message": "b", "block_ids": [pid]})
    gate.set()
    t.join(5)
    assert second.status_code == 409
    assert results["first"].status_code == 200


def test_restore(tmp_path, pdf_bytes):
    client, _, slug = imported(tmp_path, pdf_bytes,
                               [blocks_out([{"type": "paragraph", "text": "新"}])])
    original = client.get(f"/api/papers/{slug}/note").json()
    pid = original["blocks"][1]["id"]
    snap = client.post(f"/api/papers/{slug}/edit", json={"message": "改", "block_ids": [pid]}).json()["snapshot"]
    changed = json.loads(json.dumps(original))
    changed["blocks"][1]["text"] = "前端套用後的新內容"
    client.put(f"/api/papers/{slug}/note", json=changed)
    assert client.post(f"/api/papers/{slug}/restore", json={"snapshot": snap}).json() == original
    assert client.post(f"/api/papers/{slug}/restore", json={"snapshot": "../x"}).status_code == 404
