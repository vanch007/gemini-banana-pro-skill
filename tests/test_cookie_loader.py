#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from banana_pro import (  # noqa: E402
    COCKPIT_IMAGE_MODEL,
    build_cockpit_body,
    cockpit_aspect_ratio,
    cockpit_account_priority,
    cockpit_image_size,
    cockpit_is_pro,
    cockpit_model_names,
    cockpit_subscription_tier,
    load_batch_manifest,
    load_cookies_with_meta,
    pick_useful_cookies,
    run_cockpit_batch,
)


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

    def test_cockpit_model_names_reads_quota_models(self) -> None:
        account = {
            "quota": {
                "models": [
                    {"model_id": COCKPIT_IMAGE_MODEL},
                    {"id": "gemini-3-pro"},
                ]
            }
        }
        self.assertEqual(
            cockpit_model_names(account),
            [COCKPIT_IMAGE_MODEL, "gemini-3-pro"],
        )

    def test_cockpit_account_priority_prefers_pro_then_current(self) -> None:
        free_current = {
            "id": "free-current",
            "email": "free@example.com",
            "quota": {"subscription_tier": "free-tier"},
        }
        pro_other = {
            "id": "pro-other",
            "email": "pro@example.com",
            "quota": {"subscription_tier": "g1-pro-tier"},
        }
        pro_current = {
            "id": "pro-current",
            "email": "current@example.com",
            "quota": {"subscription_tier": "g1-pro-tier"},
        }
        ordered = sorted(
            [free_current, pro_other, pro_current],
            key=lambda account: cockpit_account_priority(account, "pro-current"),
        )
        self.assertEqual(
            [account["id"] for account in ordered],
            ["pro-current", "pro-other", "free-current"],
        )
        self.assertEqual(cockpit_subscription_tier(pro_current), "g1-pro-tier")
        self.assertTrue(cockpit_is_pro(pro_current))
        self.assertFalse(cockpit_is_pro(free_current))

    def test_cockpit_aspect_ratio_maps_dimensions(self) -> None:
        self.assertEqual(cockpit_aspect_ratio("1920x1080"), "16:9")
        self.assertEqual(cockpit_aspect_ratio("4:5"), "4:5")

    def test_cockpit_image_size_prefers_explicit_value(self) -> None:
        args = Namespace(image_size="2k", quality="hd")
        self.assertEqual(cockpit_image_size(args), "2K")

    def test_cockpit_body_contains_image_config(self) -> None:
        args = Namespace(
            prompt="Draw a red square",
            image=[],
            size="16:9",
            image_size=None,
            quality="2k",
        )
        body = build_cockpit_body(args, "project-123")
        self.assertEqual(body["model"], COCKPIT_IMAGE_MODEL)
        self.assertEqual(body["requestType"], "image_gen")
        self.assertEqual(
            body["request"]["generationConfig"]["imageConfig"],
            {"aspectRatio": "16:9", "imageSize": "2K"},
        )

    def test_batch_manifest_normalizes_images_and_rejects_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch.json"
            path.write_text(
                json.dumps(
                    {
                        "defaults": {"size": "1:1"},
                        "tasks": [
                            {"id": "main_01", "prompt": "First", "image": "a.jpg"},
                            {"id": "main_02", "prompt": "Second", "images": ["b.jpg"]},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            loaded_path, defaults, tasks = load_batch_manifest(path)
            self.assertEqual(loaded_path, path.resolve())
            self.assertEqual(defaults["size"], "1:1")
            self.assertEqual(tasks[0]["images"], ["a.jpg"])
            self.assertEqual(tasks[1]["images"], ["b.jpg"])

            path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {"id": "same", "prompt": "First"},
                            {"id": "same", "prompt": "Second"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                load_batch_manifest(path)


class CockpitBatchTest(unittest.IsolatedAsyncioTestCase):
    def batch_args(self, manifest: Path, status: Path, workers: int = 2) -> Namespace:
        return Namespace(
            auth_source="cockpit",
            manifest=str(manifest),
            status_file=str(status),
            workers=workers,
            account_tier="pro",
            resume=False,
            json=True,
            cockpit_dir=None,
            cockpit_account_id=None,
            cockpit_account_email=None,
            proxy=None,
            skip_verify=False,
            no_account_failover=False,
            request_timeout=30,
            watchdog_timeout=30,
            refresh_interval=60,
            no_auto_refresh=True,
            keepalive_seconds=0,
            refresh_browser_cookies=False,
            browser="auto",
            browser_profile=None,
            cookie_db=None,
            no_persist=True,
            verbose=False,
            model="",
            account_index=None,
        )

    def write_manifest(self, root: Path, task_ids: list[str]) -> Path:
        manifest = root / "batch.json"
        manifest.write_text(
            json.dumps(
                {
                    "defaults": {"size": "1:1", "image_size": "1K"},
                    "tasks": [
                        {
                            "id": task_id,
                            "prompt": f"Generate {task_id}",
                            "output_dir": str(root / task_id),
                            "prefix": task_id,
                        }
                        for task_id in task_ids
                    ],
                }
            ),
            encoding="utf-8",
        )
        return manifest

    async def test_batch_uses_distinct_accounts_concurrently(self) -> None:
        accounts = [
            {"id": "account-a", "email": "a@example.com", "quota": {"subscription_tier": "g1-pro-tier"}},
            {"id": "account-b", "email": "b@example.com", "quota": {"subscription_tier": "g1-pro-tier"}},
        ]
        started: set[str] = set()
        both_started = asyncio.Event()

        async def generate(args: Namespace, account: dict) -> dict:
            started.add(account["id"])
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1)
            return {"images": [{"path": str(Path(args.output_dir) / "generated.jpg")}]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(root, ["one", "two"])
            status = root / "status.json"
            with (
                patch("banana_pro.select_cockpit_accounts", return_value=accounts),
                patch("banana_pro.generate_cockpit_with_account", side_effect=generate),
            ):
                result = await run_cockpit_batch(self.batch_args(manifest, status))
            payload = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertEqual(payload["counts"]["pass"], 2)
            self.assertEqual(
                {task["account_id"] for task in payload["tasks"]},
                {"account-a", "account-b"},
            )

    async def test_batch_requeues_failed_task_to_another_account(self) -> None:
        accounts = [
            {"id": "account-a", "email": "a@example.com", "quota": {"subscription_tier": "g1-pro-tier"}},
            {"id": "account-b", "email": "b@example.com", "quota": {"subscription_tier": "g1-pro-tier"}},
        ]

        async def generate(args: Namespace, account: dict) -> dict:
            if account["id"] == "account-a":
                raise RuntimeError("quota exhausted")
            return {"images": [{"path": str(Path(args.output_dir) / "generated.jpg")}]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_manifest(root, ["retry"])
            status = root / "status.json"
            with (
                patch("banana_pro.select_cockpit_accounts", return_value=accounts),
                patch("banana_pro.generate_cockpit_with_account", side_effect=generate),
            ):
                result = await asyncio.wait_for(
                    run_cockpit_batch(self.batch_args(manifest, status)),
                    timeout=2,
                )
            payload = json.loads(status.read_text(encoding="utf-8"))
            task = payload["tasks"][0]
            self.assertEqual(result, 0)
            self.assertEqual(task["status"], "pass")
            self.assertEqual(task["account_id"], "account-b")
            self.assertEqual([attempt["status"] for attempt in task["attempts"]], ["fail", "pass"])


if __name__ == "__main__":
    unittest.main()
