#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from banana_pro import load_cookies_with_meta, pick_useful_cookies  # noqa: E402


class CookieLoaderTest(unittest.TestCase):
    def test_flat_cookie_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookies.json"
            path.write_text(json.dumps({"__Secure-1PSID": "abc"}), encoding="utf-8")
            cookies, _ = load_cookies_with_meta(path)
            self.assertEqual(cookies["__Secure-1PSID"], "abc")

    def test_chrome_cookie_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookies.json"
            path.write_text(
                json.dumps([{"name": "__Secure-1PSID", "value": "abc"}]),
                encoding="utf-8",
            )
            cookies, _ = load_cookies_with_meta(path)
            self.assertEqual(cookies["__Secure-1PSID"], "abc")

    def test_pick_useful_cookies_ignores_noise(self) -> None:
        cookies = pick_useful_cookies(
            [
                {"name": "__Secure-1PSID", "value": "abc"},
                {"name": "irrelevant", "value": "noise"},
                {"name": "__Secure-1PSIDTS", "value": "ts"},
            ]
        )
        self.assertEqual(cookies, {"__Secure-1PSID": "abc", "__Secure-1PSIDTS": "ts"})


if __name__ == "__main__":
    unittest.main()
