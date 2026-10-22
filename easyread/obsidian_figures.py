"""Obsidian 附图：PNG 截图、可读命名与不覆盖写入。"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import pdfwork
from .i18n import tr
from .obsidian_vault import safe_name


def export_figure(ws, block: dict, short: str, desc: str, attach_dir: Path) -> str:
    """相同文件名逐个比较内容；只重用相同内容，其余排他创建。"""
    if not block.get("box"):
        raise ValueError(tr("图片内容无法识别"))
    data = pdfwork.crop_png(ws.root, block["page"], block["box"])
    digest = hashlib.sha256(data).digest()
    num = safe_name(str(block.get("num", "x")))
    stem = f"{safe_name(short)}-圖{num}-{safe_name(desc)}"  # i18n-ok 固定的附图文件名
    number = 1
    while True:
        name = f"{stem}.png" if number == 1 else f"{stem}-{number}.png"
        path = attach_dir / name
        try:
            with open(path, "xb") as file:
                file.write(data)
        except FileExistsError:
            # 不沿符号链接重用其他目录的文件，也不覆盖同名目录。
            if not path.is_symlink() and path.is_file():
                if hashlib.sha256(path.read_bytes()).digest() == digest:
                    return name
            number += 1
            continue
        return name
