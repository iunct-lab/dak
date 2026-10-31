import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# Add parent directory to path to import main
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


class TestGrep(unittest.IsolatedAsyncioTestCase):
    """Tests for the grep content-search tool."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    async def test_grep_finds_matching_lines(self):
        self._write("a.py", "hello world\nfoo bar\nhello again\n")
        result = await main.grep("hello", self.dir)
        self.assertIn("hello world", result)
        self.assertIn("hello again", result)
        self.assertNotIn("foo bar", result)

    async def test_grep_reports_line_numbers(self):
        self._write("a.py", "alpha\nbeta target\ngamma\n")
        result = await main.grep("target", self.dir)
        self.assertIn(":2:", result)

    async def test_grep_no_match(self):
        self._write("a.py", "nothing here\n")
        result = await main.grep("zzz", self.dir)
        self.assertIn("No matches", result)

    async def test_grep_respects_glob(self):
        self._write("a.py", "target\n")
        self._write("b.txt", "target\n")
        result = await main.grep("target", self.dir, glob_pattern="*.py")
        self.assertIn("a.py", result)
        self.assertNotIn("b.txt", result)

    async def test_grep_ignore_case(self):
        self._write("a.py", "Hello HELLO\n")
        with_case = await main.grep("hello", self.dir, ignore_case=False)
        self.assertIn("No matches", with_case)
        no_case = await main.grep("hello", self.dir, ignore_case=True)
        self.assertIn("Hello HELLO", no_case)

    async def test_grep_single_file(self):
        path = self._write("a.py", "match me\nnope\n")
        result = await main.grep("match", path)
        self.assertIn("match me", result)
        self.assertNotIn("nope", result)

    async def test_grep_caps_matches(self):
        lines = [f"line {i}" for i in range(main.MAX_GREP_MATCHES + 50)]
        self._write("big.txt", "\n".join(lines) + "\n")
        result = await main.grep("line", self.dir)
        self.assertIn("truncated", result)

    async def test_grep_invalid_regex(self):
        self._write("a.py", "anything\n")
        result = await main.grep("([", self.dir)
        self.assertIn("invalid regex", result)


class TestEditFile(unittest.IsolatedAsyncioTestCase):
    """Tests for the edit_file targeted-replace tool."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def _read(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    async def test_edit_single_replace(self):
        path = self._write("a.py", "hello world\n")
        result = await main.edit_file(path, "world", "there")
        self.assertIn("Replaced 1 occurrence", result)
        self.assertEqual(self._read(path), "hello there\n")

    async def test_edit_not_found(self):
        path = self._write("a.py", "hello\n")
        result = await main.edit_file(path, "zzz", "yyy")
        self.assertIn("not found", result)
        self.assertEqual(self._read(path), "hello\n")

    async def test_edit_ambiguous_refused(self):
        path = self._write("a.py", "a b a\n")
        result = await main.edit_file(path, "a", "c")
        self.assertIn("occurs 2 times", result)
        self.assertEqual(self._read(path), "a b a\n")

    async def test_edit_replace_all(self):
        path = self._write("a.py", "x y x z x\n")
        result = await main.edit_file(path, "x", "q", replace_all=True)
        self.assertIn("Replaced 3 occurrence", result)
        self.assertEqual(self._read(path), "q y q z q\n")

    async def test_edit_read_error(self):
        with patch("builtins.open", side_effect=FileNotFoundError("nope")):
            result = await main.edit_file("/nope", "a", "b")
            self.assertIn("Error reading file", result)

    async def test_edit_write_error(self):
        path = self._write("a.py", "hello\n")
        real_open = open

        def fake_open(p, mode="r", *args, **kwargs):
            if "w" in mode:
                raise PermissionError("denied")
            return real_open(p, mode, *args, **kwargs)

        with patch("builtins.open", side_effect=fake_open):
            result = await main.edit_file(path, "hello", "x")
            self.assertIn("Error writing file", result)
        self.assertEqual(self._read(path), "hello\n")


if __name__ == "__main__":
    unittest.main()
