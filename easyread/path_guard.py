"""本機路徑的信任檢查（2026-10-23 資安加固）：拿到寫入令牌的其他帳號／沙箱程式，不能讓服務
執行它放的程式（cli_guard），也不能讓服務把它指定的、你讀得到但它讀不到的檔案匯入文獻庫再用 GET 讀走（bulk、zotero）。

規則仿 sshd StrictModes：
- 檔案與它到 / 的每一層目錄（原路徑與追完符號連結的真實路徑都查）屬於自己或 root，而且其他人不可寫；
  群組可寫只在該群組只有自己（與 root）時接受（例如單人 Mac 上 Homebrew 的 /opt/homebrew/bin 是 admin 可寫）。
- 不能在暫存／共用目錄底下（/tmp、/var/folders、$TMPDIR、/Users/Shared、~/Library/Containers……）。
Windows 沒有 uid，不檢查。
"""
from __future__ import annotations

import os
import stat


def _untrusted_roots() -> list[str]:
    home = os.path.expanduser("~")
    roots = ["/tmp", "/private/tmp", "/var/tmp", "/private/var/tmp", "/var/folders", "/private/var/folders", "/Users/Shared",
             os.path.join(home, "Library", "Containers"), os.path.join(home, "Library", "Group Containers")]
    if os.environ.get("TMPDIR"):
        roots.append(os.environ["TMPDIR"])
    out = set()
    for r in roots:
        out.add(os.path.normpath(r))
        out.add(os.path.realpath(r))
    return sorted(out)


def _group_only_me(gid: int) -> bool:
    try:
        import grp
        import pwd
        me = pwd.getpwuid(os.getuid()).pw_name
        members = set(grp.getgrgid(gid).gr_mem) | {u.pw_name for u in pwd.getpwall() if u.pw_gid == gid}
    except (ImportError, KeyError, OSError):
        return False
    return members <= {me, "root"}


def _safe_node(path: str, owners: tuple) -> bool:
    try:
        st = os.stat(path)
    except OSError:
        return False
    if st.st_uid not in owners or st.st_mode & stat.S_IWOTH:
        return False
    return not (st.st_mode & stat.S_IWGRP) or _group_only_me(st.st_gid)


def in_untrusted_dir(value: str) -> bool:
    roots = _untrusted_roots()
    for path in {os.path.normpath(os.path.abspath(value)), os.path.realpath(value)}:
        if any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots):
            return True
    return False


def trusted_path(value: str, *, leaf_mine: bool = False) -> bool:
    """value 與每一層上層目錄都屬於自己或 root、別人不可寫，且不在暫存／共用目錄。
    leaf_mine=True：value 本身必須屬於自己（不接受 root 的檔案，用於「匯入使用者自己的資料」）。"""
    if not hasattr(os, "getuid"):
        return True
    if not value or not os.path.isabs(str(value)):
        return False
    value = str(value)
    if in_untrusted_dir(value):
        return False
    uid = os.getuid()
    for path in {os.path.normpath(value), os.path.realpath(value)}:
        node, first = path, True
        while True:
            if not _safe_node(node, (uid,) if (first and leaf_mine) else (uid, 0)):
                return False
            first = False
            parent = os.path.dirname(node)
            if parent == node:
                break
            node = parent
    return True


def under_home(value: str) -> bool:
    if not hasattr(os, "getuid"):
        return True
    home = os.path.realpath(os.path.expanduser("~"))
    real = os.path.realpath(str(value))
    return real == home or real.startswith(home.rstrip("/") + "/")


def mine_file(value) -> bool:
    """要匯入的單一檔案：真實路徑屬於自己、別人不可寫，且不在暫存／共用目錄。"""
    if not hasattr(os, "getuid"):
        return True
    try:
        st = os.stat(str(value))
    except OSError:
        return False
    return st.st_uid == os.getuid() and not st.st_mode & stat.S_IWOTH and not in_untrusted_dir(str(value))
