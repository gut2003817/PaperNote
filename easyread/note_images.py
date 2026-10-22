"""笔记里的图片：存在论文目录的 note-images/ 下，文件名 = 内容 SHA-256 前 32 位 + 扩展名（内容定址，同一张图只存一份）。

类型只认文件头（魔术字节）：PNG / JPEG / WebP / GIF；不认客户端报的 Content-Type 和扩展名，也不收 SVG。
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import time
from pathlib import Path

from .app.i18n import tr

DIR = "note-images"
MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 80_000_000  # 防“解压炸弹”：几十 KB 的文件解出几十亿像素
NAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp|gif)$")
_EXT = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "GIF": "gif"}


def sniff(data: bytes) -> str | None:
    """按文件头判断类型，返回 Pillow 的格式名；不是这四种就返回 None。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def validate(data: bytes) -> str:
    """返回扩展名；内容不合格就抛 ValueError（给用户看的中文消息）。"""
    if not data:
        raise ValueError(tr("没有收到图片内容"))
    if len(data) > MAX_BYTES:
        raise ValueError(tr("图片太大（上限 {mb} MB）", mb=MAX_BYTES // 1024 // 1024))
    fmt = sniff(data)
    if not fmt:
        raise ValueError(tr("只支持 PNG、JPEG、WebP、GIF 图片"))
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            if img.format != fmt:
                raise ValueError(tr("图片内容无法识别"))
            w, h = img.size
            if w * h > MAX_PIXELS:
                raise ValueError(tr("图片尺寸太大"))
            img.verify()
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 Pillow 对坏文件抛各种异常
        raise ValueError(tr("图片内容无法识别")) from None
    return _EXT[fmt]


def save(root: Path, data: bytes) -> str:
    """校验后存进 root/note-images/，返回文件名。已有同名（同内容）文件就不再写。原子写入。"""
    ext = validate(data)
    name = hashlib.sha256(data).hexdigest()[:32] + "." + ext
    folder = Path(root) / DIR
    if folder.is_symlink():
        raise ValueError(tr("笔记图片目录不是普通文件夹"))
    folder.mkdir(exist_ok=True)
    target = folder / name
    if target.is_file() and not target.is_symlink() and target.stat().st_size == len(data):
        return name
    tmp = folder / f".{name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return name


def path_of(root: Path, name: str) -> Path | None:
    """读取用：名字必须完全符合 NAME_RE，且是目录里的普通文件（符号链接一律不要）。"""
    if not NAME_RE.fullmatch(name or ""):
        return None
    folder = Path(root) / DIR
    p = folder / name
    if folder.is_symlink() or p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(Path(root).resolve()):
        return None
    return p


MD_RE = re.compile(r"!\[[^\]\n]*\]\(" + DIR + r"/([0-9a-f]{32}\.(?:png|jpg|webp|gif))\)")


def used_in(texts) -> list[str]:
    """从一批 Markdown 文字里找出引用的笔记图片文件名（去重，保持出现顺序）。"""
    seen: dict[str, None] = {}
    for t in texts:
        for m in MD_RE.finditer(t or ""):
            seen.setdefault(m.group(1))
    return list(seen)
