"""論文資料夾的讀寫。所有路徑都經過這裡，防止 slug／檔名穿越目錄。"""
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .schema import Note

_SLUG_RE = re.compile(r"^[a-z0-9-]{1,80}$")
_SNAPSHOT_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}\.json$")
_FIGURE_RE = re.compile(r"^[\w.-]+\.png$")


class NotFound(Exception):
    pass


@dataclass
class PaperInfo:
    slug: str
    title: str
    created: float
    has_note: bool


def _slugify(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "paper"
    return f"{base}-{uuid4().hex[:6]}"


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Storage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def paper_dir(self, slug: str) -> Path:
        if not _SLUG_RE.match(slug):
            raise NotFound(slug)
        d = self.root / slug
        if not d.is_dir():
            raise NotFound(slug)
        return d

    def create_paper(self, title: str, pdf_bytes: bytes) -> str:
        slug = _slugify(title)
        d = self.root / slug
        (d / "figures").mkdir(parents=True)
        (d / "history").mkdir()
        (d / "paper.pdf").write_bytes(pdf_bytes)
        _atomic_write(d / "meta.json",
                      json.dumps({"title": title, "created": time.time()}, ensure_ascii=False))
        return slug

    def list_papers(self) -> list[PaperInfo]:
        out = []
        for d in self.root.iterdir():
            meta = d / "meta.json"
            if d.is_dir() and meta.exists():
                m = json.loads(meta.read_text(encoding="utf-8"))
                out.append(PaperInfo(d.name, m["title"], m["created"], (d / "note.json").exists()))
        return sorted(out, key=lambda p: p.created, reverse=True)

    def figures_dir(self, slug: str) -> Path:
        return self.paper_dir(slug) / "figures"

    def figure_path(self, slug: str, name: str) -> Path:
        if not _FIGURE_RE.match(name):
            raise NotFound(name)
        p = self.figures_dir(slug) / name
        if not p.is_file():
            raise NotFound(name)
        return p

    def read_note(self, slug: str) -> Note:
        p = self.paper_dir(slug) / "note.json"
        if not p.exists():
            raise NotFound(f"{slug}/note.json")
        return Note.model_validate_json(p.read_text(encoding="utf-8"))

    def write_note(self, slug: str, note: Note) -> None:
        _atomic_write(self.paper_dir(slug) / "note.json",
                      note.model_dump_json(indent=2, exclude_none=True))

    def read_summary(self, slug: str) -> str:
        p = self.paper_dir(slug) / "summary.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def write_summary(self, slug: str, text: str) -> None:
        _atomic_write(self.paper_dir(slug) / "summary.md", text)

    def snapshot(self, slug: str) -> str:
        d = self.paper_dir(slug)
        p = d / "note.json"
        if not p.exists():
            raise NotFound(f"{slug}/note.json")
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:4]}.json"
        _atomic_write(d / "history" / name, p.read_text(encoding="utf-8"))
        return name

    def restore(self, slug: str, name: str) -> Note:
        if not _SNAPSHOT_RE.match(name):
            raise NotFound(name)
        p = self.paper_dir(slug) / "history" / name
        if not p.is_file():
            raise NotFound(name)
        note = Note.model_validate_json(p.read_text(encoding="utf-8"))
        self.write_note(slug, note)
        return note

    def append_chat(self, slug: str, entry: dict) -> None:
        line = json.dumps({**entry, "ts": time.time()}, ensure_ascii=False)
        with open(self.paper_dir(slug) / "chat.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read_chat(self, slug: str) -> list[dict]:
        p = self.paper_dir(slug) / "chat.jsonl"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
