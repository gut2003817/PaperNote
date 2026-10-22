"""Vault 验证、文件名与排他写入，只使用临时目录。"""
from __future__ import annotations

import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from easyread import obsidian_vault


class ObsidianVaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_check_vault_rejects_relative_missing_file_symlink_and_dotdot(self):
        file = self.root / "file"
        file.write_bytes(b"keep")
        link = self.root / "link"
        link.symlink_to(self.root, target_is_directory=True)
        broken = self.root / "broken"
        broken.symlink_to(self.root / "missing", target_is_directory=True)
        before = set(self.root.iterdir())
        for path in ("relative", "", str(self.root / "missing"), str(file),
                     str(link), str(link) + "/", str(broken), str(self.root / ".." / self.root.name)):
            with self.subTest(path=path), self.assertRaises(ValueError):
                obsidian_vault.check_vault(path)
        self.assertEqual(set(self.root.iterdir()), before)
        self.assertEqual(file.read_bytes(), b"keep")

    def test_check_vault_accepts_path_with_space(self):
        vault = self.root / "Obsidian Vault"
        vault.mkdir()
        self.assertEqual(obsidian_vault.check_vault(str(vault)), vault.resolve())
        self.assertEqual(list(vault.iterdir()), [])

    def test_check_vault_rejects_unwritable(self):
        # 模拟实际创建失败，避免测试以高权限执行时 chmod 失效。
        with patch("tempfile.NamedTemporaryFile", side_effect=PermissionError("denied")) as create:
            with self.assertRaises(ValueError):
                obsidian_vault.check_vault(str(self.root))
        create.assert_called_once()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_note_dirs_creates_only_two_folders(self):
        settings = self.root / ".obsidian"
        settings.mkdir()
        config = settings / "app.json"
        config.write_bytes(b'{"keep": true}')
        note = self.root / "existing.md"
        note.write_bytes(b"keep")
        notes, figures = obsidian_vault.note_dirs(self.root)
        self.assertEqual(notes, self.root / "論文筆記")
        self.assertEqual(figures, notes / "附圖")
        self.assertEqual(set(self.root.iterdir()), {settings, note, notes})
        self.assertEqual(list(notes.iterdir()), [figures])
        self.assertEqual(list(figures.iterdir()), [])
        self.assertEqual(list(settings.iterdir()), [config])
        self.assertEqual(config.read_bytes(), b'{"keep": true}')
        self.assertEqual(note.read_bytes(), b"keep")
        self.assertEqual(obsidian_vault.note_dirs(self.root), (notes, figures))

    def test_note_dirs_rejects_symlinked_folder(self):
        for name in ("論文筆記", "論文筆記/附圖"):
            for broken in (False, True):
                with self.subTest(name=name, broken=broken), tempfile.TemporaryDirectory() as tmp:
                    vault = Path(tmp)
                    target = vault / "target"
                    if not broken:
                        target.mkdir()
                    link = vault / name
                    link.parent.mkdir(exist_ok=True)
                    link.symlink_to(target, target_is_directory=True)
                    with self.assertRaises(ValueError):
                        obsidian_vault.note_dirs(vault)
                    self.assertTrue(link.is_symlink())
                    if not broken:
                        self.assertEqual(list(target.iterdir()), [])

    def test_note_dirs_rejects_file(self):
        for name in ("論文筆記", "論文筆記/附圖"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                vault = Path(tmp)
                file = vault / name
                file.parent.mkdir(exist_ok=True)
                file.write_bytes(b"keep")
                with self.assertRaises(ValueError):
                    obsidian_vault.note_dirs(vault)
                self.assertEqual(file.read_bytes(), b"keep")

    def test_safe_name_cases(self):
        cases = [("a/\\:*?\"<>|b", "ab"), ("x" * 50, "x" * 40),
                 ("", "paper"), ("/\x00\x1f\x7f\x85", "paper"),
                 ("全中文論文標題", "全中文論文標題"), ("two words", "two-words"),
                 ("  two   words  ", "two-words"), ("a\x00b\nc", "abc")]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(obsidian_vault.safe_name(value), expected)
        self.assertEqual(obsidian_vault.safe_name("論文標題", limit=2), "論文")

    def test_write_new_never_overwrites(self):
        first = obsidian_vault.write_new(self.root, "a", ".md", b"first")
        second = obsidian_vault.write_new(self.root, "a", ".md", b"second")
        self.assertEqual(first, self.root / "a.md")
        self.assertEqual(second, self.root / "a-2.md")
        self.assertEqual(first.read_bytes(), b"first")
        self.assertEqual(second.read_bytes(), b"second")

    def test_write_new_numbers_after_collision(self):
        for name in ("a.png", "a-2.png", "a-3.png"):
            (self.root / name).write_bytes(b"keep")
        result = obsidian_vault.write_new(self.root, "a", ".png", b"new")
        self.assertEqual(result, self.root / "a-4.png")
        self.assertEqual(result.read_bytes(), b"new")
        for name in ("a.png", "a-2.png", "a-3.png"):
            self.assertEqual((self.root / name).read_bytes(), b"keep")

    def test_write_new_handles_creation_race(self):
        real_open = open

        def racing_open(path, mode):
            self.assertEqual(mode, "xb")
            if path == self.root / "a.md":
                with real_open(path, "xb") as file:
                    file.write(b"other writer")
            return real_open(path, mode)

        with patch("builtins.open", side_effect=racing_open):
            result = obsidian_vault.write_new(self.root, "a", ".md", b"new")
        self.assertEqual(result, self.root / "a-2.md")
        self.assertEqual((self.root / "a.md").read_bytes(), b"other writer")
        self.assertEqual(result.read_bytes(), b"new")

    def test_write_new_does_not_follow_existing_symlink(self):
        target = self.root / "target"
        target.write_bytes(b"keep")
        (self.root / "a.md").symlink_to(target)
        result = obsidian_vault.write_new(self.root, "a", ".md", b"new")
        self.assertEqual(result, self.root / "a-2.md")
        self.assertEqual(target.read_bytes(), b"keep")

    def test_stamp_format(self):
        self.assertEqual(obsidian_vault.stamp(datetime(2026, 1, 2, 3, 4, 5)), "20260102-030405")
        self.assertIsNotNone(re.fullmatch(r"\d{8}-\d{6}", obsidian_vault.stamp()))
