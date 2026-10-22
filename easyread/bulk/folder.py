"""导入整个文件夹：递归找出里面的 PDF，文件夹层级就是分类层级。

选的是 D:/论文，里面有 CV/YOLO/a.pdf，这篇就放进“论文/CV/YOLO”；直接放在 D:/论文 下的放进“论文”。
隐藏文件夹（. 开头）和快捷方式指向的文件夹不进去。"""
from __future__ import annotations

import os
from pathlib import Path

from .. import path_guard
from ..app.i18n import tr
from ..zotero.reader import Entry, Snapshot

MAX_FILES = 5000


def read(path: str) -> Snapshot:
    root = Path(path).expanduser()
    if not root.is_dir():
        raise ValueError(tr("找不到这个文件夹：{path}", path=str(root)))
    root = root.resolve()
    if not path_guard.trusted_path(str(root), leaf_mine=True):  # 別人的、別人可寫的、暫存／共用資料夾不匯入
        raise ValueError(tr("这个文件夹不属于你、其他用户能写入，或位于临时/共享文件夹，不能导入：{path}", path=str(root)))
    top = root.name or str(root).rstrip("\\/:")  # 选的是盘符根目录时没有名字
    entries: list[Entry] = []
    cats: list[str] = []
    for d, dirs, files in os.walk(root):  # 默认不跟进快捷方式 / 软链接指向的文件夹
        dirs[:] = sorted(x for x in dirs if not x.startswith("."))
        rel = Path(d).relative_to(root).parts
        cat = "/".join(p.replace("/", "／") for p in (top, *rel))
        pdfs = sorted(f for f in files if f.lower().endswith(".pdf") and not f.startswith("."))
        if pdfs and cat not in cats:
            # 祖先也记下，空着的中间层也按文件夹顺序出现
            for k in range(1, len(rel) + 2):
                anc = "/".join(cat.split("/")[:k])
                if anc not in cats:
                    cats.append(anc)
        for f in pdfs:
            if len(entries) >= MAX_FILES:
                raise ValueError(tr("这个文件夹里的 PDF 超过 {n} 个，请分几次导入，每次选一个子文件夹", n=MAX_FILES))
            pdf = Path(d) / f
            if not path_guard.mine_file(pdf):  # 例如指到別處的符號連結、別人的檔案：不匯入，列在“没有 PDF”裡
                entries.append(Entry(key=str(Path(d, f).relative_to(root)), meta={"title_en": pdf.stem}, cats=[cat],
                                     missing=tr("文件不属于你或位于临时/共享文件夹，已跳过：{path}", path=str(pdf))))
                continue
            entries.append(Entry(key=str(Path(d, f).relative_to(root)), meta={}, cats=[cat], pdf=pdf))
    return Snapshot(entries=entries, collections=cats)
