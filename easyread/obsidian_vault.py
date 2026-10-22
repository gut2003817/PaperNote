"""Obsidian vault 路径校验、文件名与不覆盖写入。"""
from __future__ import annotations

import re
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path

from .app.i18n import tr

_BAD_NAME = re.compile(r'[/\\:*?"<>|]')


def check_vault(path: str) -> Path:
    """验证用户指定的根目录，探测可写性后不留下临时文件。"""
    vault = Path(path)
    if not vault.is_absolute() or ".." in vault.parts:
        raise ValueError(tr("请输入完整的文件夹路径"))
    try:
        if vault.is_symlink():
            raise ValueError(tr("Obsidian 文件夹不能是符号链接或目录联接，请选择普通文件夹：{path}", path=path))
        if not vault.exists():
            raise ValueError(tr("路径不存在：{path}", path=path))
        if not vault.is_dir():
            raise ValueError(tr("请输入完整的文件夹路径"))
        vault = vault.resolve()
        with tempfile.NamedTemporaryFile(dir=vault):
            pass
    except OSError as exc:
        raise ValueError(tr("Obsidian 文件夹不可写，请检查权限")) from exc
    return vault


def note_dirs(vault: Path) -> tuple[Path, Path]:
    """只创建笔记和附图目录，拒绝占用这些名字的文件或符号链接。"""
    notes = vault / "論文筆記"  # i18n-ok 固定的 vault 子目录名，不随界面语言改变
    figures = notes / "附圖"  # i18n-ok 固定的 vault 子目录名
    for directory in (notes, figures):
        if directory.is_symlink():
            raise ValueError(tr("Obsidian 里的“论文笔记”文件夹不能是符号链接，请改成普通文件夹：{path}", path=str(directory)))
        try:
            directory.mkdir(exist_ok=True)
        except FileExistsError as exc:
            raise ValueError(tr("Obsidian 文件夹里已有同名的文件，不会覆盖：{name}", name=str(directory))) from exc
        except OSError as exc:
            raise ValueError(tr("Obsidian 文件夹不可写，请检查权限")) from exc
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(tr("Obsidian 文件夹里已有同名的文件，不会覆盖：{name}", name=str(directory)))
    return notes, figures


def safe_name(s: str, limit: int = 40) -> str:
    """删除禁用字符，合并空白并限制文件名长度。"""
    s = _BAD_NAME.sub("", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Cc")
    # 開頭的點會變成隱藏檔（Obsidian 不索引），結尾的點在部分系統不合法
    return "-".join(s.split())[:limit].strip(".") or "paper"


def write_new(dir_: Path, stem: str, suffix: str, data: bytes) -> Path:
    """排他创建；同名时递增编号，不先检查路径是否存在。"""
    number = 1
    while True:
        name = stem if number == 1 else f"{stem}-{number}"
        path = dir_ / f"{name}{suffix}"
        try:
            with open(path, "xb") as file:
                file.write(data)
        except FileExistsError:
            number += 1
            continue
        return path


def stamp(now: datetime | None = None) -> str:
    return (now if now is not None else datetime.now()).strftime("%Y%m%d-%H%M%S")
