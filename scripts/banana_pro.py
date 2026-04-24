#!/usr/bin/env python3
"""Standalone Gemini Web Nano Banana Pro image CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))

try:
    import browser_cookie3 as bc3  # noqa: E402
    from gemini_webapi import GeminiClient, logger, set_log_level  # noqa: E402
    from gemini_webapi.constants import Model  # noqa: E402
    from gemini_webapi.exceptions import AuthError, GeminiError  # noqa: E402
    from gemini_webapi.types.image import GeneratedImage, WebImage  # noqa: E402
    from gemini_webapi.utils.load_browser_cookies import load_browser_cookies  # noqa: E402
except ModuleNotFoundError as exc:
    if exc.name in {"curl_cffi", "loguru", "orjson", "pydantic", "browser_cookie3"}:
        raise SystemExit(
            f"Missing dependency '{exc.name}'. Run: python3 -m pip install -r {ROOT / 'requirements.txt'}"
        ) from exc
    raise


def parse_expiry(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return int(float(raw))
        except ValueError:
            pass
        try:
            return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return None
    return None


def load_cookies_with_meta(path: str | Path) -> tuple[dict[str, str], dict[str, Any]]:
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    cookies: dict[str, str] = {}
    meta: dict[str, Any] = {}

    def upsert(name: Any, value: Any, expires_raw: Any = None) -> None:
        if not isinstance(name, str) or not name:
            return
        if not isinstance(value, str) or not value:
            return
        cookies[name] = value
        exp = parse_expiry(expires_raw)
        meta[name] = {
            "expires_raw": expires_raw,
            "expires_epoch": exp,
            "expires_iso": (
                datetime.fromtimestamp(exp, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
                if exp is not None
                else None
            ),
        }

    def handle_obj(item: dict[str, Any]) -> None:
        upsert(
            item.get("name"),
            item.get("value"),
            item.get("expirationDate")
            or item.get("expires")
            or item.get("expiry")
            or item.get("expiresDate"),
        )

    if isinstance(data, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        for k, v in data.items():
            upsert(k, v)
        return cookies, meta
    if isinstance(data, dict) and isinstance(data.get("cookies"), dict):
        for k, v in data["cookies"].items():
            upsert(k, v)
        if cookies:
            return cookies, meta
    if isinstance(data, dict) and isinstance(data.get("cookies"), list):
        for item in data["cookies"]:
            if isinstance(item, dict):
                handle_obj(item)
        if cookies:
            return cookies, meta
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                handle_obj(item)
        if cookies:
            return cookies, meta
    raise SystemExit("Unsupported cookie JSON format.")


DEFAULT_COOKIE_PATH = ROOT / "cookies.json"
CHROME_ROOT = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
SUPPORTED_BROWSERS = {
    "auto": None,
    "chrome": "chrome",
    "chromium": "chromium",
    "arc": "arc",
    "brave": "brave",
    "edge": "edge",
    "safari": "safari",
    "firefox": "firefox",
    "opera": "opera",
    "opera_gx": "opera_gx",
    "vivaldi": "vivaldi",
    "librewolf": "librewolf",
}
REQUIRED_COOKIE_NAMES = {"__Secure-1PSID"}
USEFUL_COOKIE_NAMES = {
    "__Secure-1PSID",
    "__Secure-1PSIDTS",
    "__Secure-1PSIDCC",
    "__Secure-1PSIDRTS",
    "__Secure-1PSIDRCC",
    "__Secure-3PSID",
    "__Secure-3PSIDTS",
    "__Secure-3PSIDCC",
    "__Secure-3PSIDRTS",
    "__Secure-3PSIDRCC",
    "NID",
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
}
def save_cookie_dict(
    path: str | Path,
    cookies: dict[str, str],
    source: str | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "updated_at": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "cookies": dict(sorted(cookies.items())),
    }
    if source:
        payload["source"] = source
    if extra_meta:
        payload.update(extra_meta)
    Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    Path(path).expanduser().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def persist_cookies(path: str | Path, original: dict[str, str], client_cookies: Any, verbose: bool = False) -> None:
    merged = dict(original)
    try:
        for cookie in client_cookies.jar:
            name = getattr(cookie, "name", None)
            value = getattr(cookie, "value", None)
            if isinstance(name, str) and isinstance(value, str) and value:
                merged[name] = value
    except Exception:
        pass
    if merged == original:
        return
    existing_meta: dict[str, Any] = {}
    try:
        existing = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            existing_meta = {k: v for k, v in existing.items() if k not in {"cookies", "updated_at"}}
    except Exception:
        existing_meta = {}
    source = existing_meta.pop("source", None) or "gemini-session"
    existing_meta["session_refreshed_at"] = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    save_cookie_dict(path, merged, source=source, extra_meta=existing_meta)
    if verbose:
        changed = [k for k in merged if merged[k] != original.get(k)]
        logger.debug(f"Persisted cookies ({', '.join(changed)})")


def resolve_cookie_path(args: argparse.Namespace) -> str | None:
    return args.cookies_json or os.getenv("GEMINI_COOKIES_JSON") or str(DEFAULT_COOKIE_PATH)


def pick_useful_cookies(cookie_list: Any) -> dict[str, str]:
    current: dict[str, str] = {}
    for item in cookie_list:
        if isinstance(item, dict):
            name = item.get("name")
            value = item.get("value")
        else:
            name = getattr(item, "name", None)
            value = getattr(item, "value", None)
            if getattr(item, "is_expired", lambda: False)():
                continue
        if name in USEFUL_COOKIE_NAMES and isinstance(value, str) and value:
            current[name] = value
    return current


def chrome_profile_cookie_paths() -> list[tuple[str, Path]]:
    if not CHROME_ROOT.exists():
        return []
    candidates: list[tuple[str, Path]] = []
    for profile_dir in sorted(CHROME_ROOT.iterdir()):
        if not profile_dir.is_dir():
            continue
        if profile_dir.name != "Default" and not profile_dir.name.startswith("Profile "):
            continue
        for cookie_path in [profile_dir / "Cookies", profile_dir / "Network" / "Cookies"]:
            if cookie_path.exists():
                candidates.append((profile_dir.name, cookie_path))
                break
    return candidates


def read_chrome_profile_info(profile_name: str) -> dict[str, Any]:
    profile_dir = CHROME_ROOT / profile_name
    prefs_path = profile_dir / "Preferences"
    info: dict[str, Any] = {
        "profile_dir": profile_name,
        "profile_name": "",
        "emails": [],
    }
    if not prefs_path.exists():
        return info
    try:
        prefs = json.loads(prefs_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return info
    profile = prefs.get("profile") if isinstance(prefs, dict) else {}
    if isinstance(profile, dict):
        value = profile.get("name")
        if isinstance(value, str):
            info["profile_name"] = value
    account_info = prefs.get("account_info") if isinstance(prefs, dict) else []
    if isinstance(account_info, list):
        emails = [item.get("email") for item in account_info if isinstance(item, dict) and item.get("email")]
        info["emails"] = emails
    return info


def should_use_account_pool(args: argparse.Namespace) -> bool:
    if getattr(args, "no_account_failover", False):
        return False
    if args.cookies_json or args.browser_profile or args.cookie_db:
        return False
    return getattr(args, "browser", "auto") in {"auto", "chrome"}


def load_chrome_cookie_file(cookie_file: str | Path, source: str, verbose: bool = False) -> tuple[dict[str, str], str]:
    try:
        jar = bc3.chrome(cookie_file=str(Path(cookie_file).expanduser()), domain_name="google.com")
    except bc3.BrowserCookieError as exc:
        raise SystemExit(f"Could not import cookies from {source}: {exc}") from exc
    except PermissionError as exc:
        raise SystemExit(
            f"Permission denied while importing cookies from {source}. "
            "Grant Keychain/browser cookie access if macOS prompts, then retry."
        ) from exc
    except Exception as exc:
        if verbose:
            logger.exception(f"Failed to import cookies from {source}")
        raise SystemExit(f"Could not import cookies from {source}: {exc}") from exc

    cookies = pick_useful_cookies(jar)
    if not REQUIRED_COOKIE_NAMES.issubset(cookies):
        raise SystemExit(
            f"{source} does not contain active Gemini login cookies. "
            "Open https://gemini.google.com in that Chrome profile, sign in once, then retry."
        )
    return cookies, source


def load_specific_browser_cookies(
    browser: str,
    browser_profile: str | None = None,
    cookie_db: str | None = None,
    verbose: bool = False,
) -> tuple[dict[str, str], str]:
    if browser == "chrome" and cookie_db:
        return load_chrome_cookie_file(cookie_db, source=f"chrome:{Path(cookie_db).expanduser().parent.name}", verbose=verbose)
    if browser == "chrome" and browser_profile:
        profile_dir = CHROME_ROOT / browser_profile
        for cookie_path in [profile_dir / "Cookies", profile_dir / "Network" / "Cookies"]:
            if cookie_path.exists():
                return load_chrome_cookie_file(cookie_path, source=f"chrome:{browser_profile}", verbose=verbose)
        raise SystemExit(f"Chrome profile '{browser_profile}' has no readable cookie DB under {profile_dir}")

    fn_name = SUPPORTED_BROWSERS[browser]
    assert fn_name is not None
    cookie_fn = getattr(bc3, fn_name)
    try:
        jar = cookie_fn(domain_name="google.com")
    except bc3.BrowserCookieError as exc:
        raise SystemExit(f"Could not import cookies from {browser}: {exc}") from exc
    except PermissionError as exc:
        raise SystemExit(
            f"Permission denied while importing cookies from {browser}. "
            "Grant Keychain/browser cookie access if macOS prompts, then retry."
        ) from exc
    except Exception as exc:
        if verbose:
            logger.exception(f"Failed to import cookies from {browser}")
        raise SystemExit(f"Could not import cookies from {browser}: {exc}") from exc

    cookies = pick_useful_cookies(jar)
    if not REQUIRED_COOKIE_NAMES.issubset(cookies):
        raise SystemExit(
            f"{browser} does not contain active Gemini login cookies. "
            "Open https://gemini.google.com in that browser, sign in once, then retry."
        )
    return cookies, browser


def load_cookies_from_browser(
    browser: str = "auto",
    browser_profile: str | None = None,
    cookie_db: str | None = None,
    verbose: bool = False,
) -> tuple[dict[str, str], str]:
    if browser not in SUPPORTED_BROWSERS:
        choices = ", ".join(SUPPORTED_BROWSERS)
        raise SystemExit(f"Unsupported browser '{browser}'. Choose one of: {choices}")
    if browser != "auto":
        return load_specific_browser_cookies(
            browser,
            browser_profile=browser_profile,
            cookie_db=cookie_db,
            verbose=verbose,
        )

    browser_sets = load_browser_cookies("google.com", verbose=verbose)
    best_name = ""
    best_cookies: dict[str, str] = {}
    for browser_name, cookie_list in browser_sets.items():
        current = pick_useful_cookies(cookie_list)
        if REQUIRED_COOKIE_NAMES.issubset(current) and len(current) > len(best_cookies):
            best_name = browser_name
            best_cookies = current
    if not best_cookies:
        raise SystemExit(
            "Could not import Gemini cookies from local browsers. "
            "Open https://gemini.google.com in Chrome/Edge/Safari once, then retry."
        )
    return best_cookies, best_name


def ensure_cookie_file(args: argparse.Namespace) -> tuple[dict[str, str], str]:
    cookie_path = resolve_cookie_path(args)
    assert cookie_path is not None
    path = Path(cookie_path).expanduser()

    if path.exists() and not args.refresh_browser_cookies:
        try:
            cookies, _ = load_cookies_with_meta(path)
            if REQUIRED_COOKIE_NAMES.issubset(cookies):
                return cookies, str(path)
        except Exception as exc:
            if args.verbose:
                logger.warning(f"Failed to load existing cookie file {path}: {exc}")

    browser = getattr(args, "browser", "auto")
    cookies, browser_name = load_cookies_from_browser(
        browser=browser,
        browser_profile=getattr(args, "browser_profile", None),
        cookie_db=getattr(args, "cookie_db", None),
        verbose=args.verbose,
    )
    save_cookie_dict(path, cookies, source=f"browser:{browser_name}")
    if args.verbose:
        logger.debug(f"Imported Gemini cookies from {browser_name} into {path}")
    return cookies, str(path)


def make_client(args: argparse.Namespace, json_cookies: dict[str, str]) -> GeminiClient:
    psid = json_cookies.get("__Secure-1PSID") or os.getenv("GEMINI_SECURE_1PSID")
    psidts = json_cookies.get("__Secure-1PSIDTS") or os.getenv("GEMINI_SECURE_1PSIDTS")
    if not psid:
        raise SystemExit("Missing __Secure-1PSID after browser import.")

    extra = {
        k: v
        for k, v in json_cookies.items()
        if k not in {"__Secure-1PSID", "__Secure-1PSIDTS"}
    }
    client = GeminiClient(
        secure_1psid=psid,
        secure_1psidts=psidts or "",
        cookies=extra or None,
        proxy=args.proxy,
        account_index=args.account_index,
        verify=not args.skip_verify,
    )
    return client


def build_client(args: argparse.Namespace) -> tuple[GeminiClient, dict[str, str], str | None]:
    json_cookies, cookie_path = ensure_cookie_file(args)
    client = make_client(args, json_cookies)
    return client, json_cookies, cookie_path


async def init_client(args: argparse.Namespace) -> tuple[GeminiClient, dict[str, str], str | None]:
    set_log_level("DEBUG" if args.verbose else "WARNING")
    client, json_cookies, cookie_path = build_client(args)
    try:
        await client.init(
            timeout=args.request_timeout,
            auto_refresh=not args.no_auto_refresh,
            refresh_interval=args.refresh_interval,
            watchdog_timeout=args.watchdog_timeout,
            verbose=args.verbose,
        )
        return client, json_cookies, cookie_path
    except AuthError as exc:
        raise SystemExit(
            f"Authentication failed: {exc}\n"
            "Run: python3 scripts/banana_pro.py auth --browser chrome --refresh-browser-cookies\n"
            "Replace 'chrome' with the browser where Gemini is already signed in."
        ) from exc


async def cleanup(client: GeminiClient, args: argparse.Namespace, json_cookies: dict[str, str], cookie_path: str | None) -> None:
    if args.keepalive_seconds > 0:
        if args.verbose:
            logger.debug(f"Keeping Gemini client alive for {args.keepalive_seconds}s before cleanup.")
        await asyncio.sleep(args.keepalive_seconds)
    if cookie_path and not args.no_persist:
        persist_cookies(cookie_path, json_cookies, client.cookies, verbose=args.verbose)
    await client.close()


async def verify_cookie_status(args: argparse.Namespace, cookies: dict[str, str]) -> str:
    client = make_client(args, cookies)
    try:
        await client.init(
            timeout=args.request_timeout,
            auto_refresh=False,
            refresh_interval=args.refresh_interval,
            watchdog_timeout=args.watchdog_timeout,
            verbose=args.verbose,
        )
        return getattr(client.account_status, "name", str(client.account_status))
    except AuthError:
        return "AUTH_ERROR"
    finally:
        await client.close()


async def inspect_cookie_account(args: argparse.Namespace, cookies: dict[str, str]) -> dict[str, Any]:
    client = make_client(args, cookies)
    try:
        await client.init(
            timeout=args.request_timeout,
            auto_refresh=False,
            refresh_interval=args.refresh_interval,
            watchdog_timeout=args.watchdog_timeout,
            verbose=args.verbose,
        )
        models = client.list_models() or []
        return {
            "account_status": getattr(client.account_status, "name", str(client.account_status)),
            "model_count": len(models),
            "models": [
                {
                    "name": model.model_name or model.display_name,
                    "display_name": model.display_name,
                    "available": getattr(model, "is_available", True),
                    "capacity": getattr(model, "capacity", None),
                    "capacity_field": getattr(model, "capacity_field", None),
                }
                for model in models
            ],
        }
    except AuthError:
        return {
            "account_status": "AUTH_ERROR",
            "model_count": 0,
            "models": [],
        }
    finally:
        await client.close()


async def collect_chrome_account_candidates(args: argparse.Namespace) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for profile_name, cookie_path in chrome_profile_cookie_paths():
        try:
            cookies, source = load_chrome_cookie_file(cookie_path, source=f"chrome:{profile_name}", verbose=args.verbose)
        except SystemExit:
            continue
        account = await inspect_cookie_account(args, cookies)
        if args.verbose:
            logger.debug(f"Chrome profile {profile_name} auth status: {account['account_status']}")
        if account["account_status"] != "AVAILABLE":
            continue
        profile_info = read_chrome_profile_info(profile_name)
        candidates.append(
            {
                **profile_info,
                "source": source,
                "cookies": cookies,
                **account,
            }
        )

    return candidates


async def find_verified_chrome_profile(args: argparse.Namespace) -> tuple[dict[str, str], str, str, dict[str, Any]] | None:
    candidates = await collect_chrome_account_candidates(args)
    if not candidates:
        return None
    best = candidates[0]
    return best["cookies"], best["source"], best["account_status"], best


async def save_images(output: Any, args: argparse.Namespace) -> list[dict[str, Any]]:
    out_dir = Path(args.output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict[str, Any]] = []
    images = list(getattr(output, "images", []) or [])
    if not args.save_web_images:
        images = [img for img in images if isinstance(img, GeneratedImage)]
    for idx, image in enumerate(images, start=1):
        prefix = args.prefix or "banana_pro"
        suffix = "generated" if isinstance(image, GeneratedImage) else "web"
        filename = f"{prefix}_{suffix}_{idx}.png"
        kwargs = {"full_size": args.full_size} if isinstance(image, GeneratedImage) else {}
        path = await image.save(path=str(out_dir), filename=filename, verbose=args.verbose, **kwargs)
        saved.append(
            {
                "path": str(path),
                "type": "generated" if isinstance(image, GeneratedImage) else "web",
                "url": getattr(image, "url", ""),
                "title": getattr(image, "title", ""),
            }
        )
    return saved


def print_result(output: Any, saved: list[dict[str, Any]], args: argparse.Namespace) -> None:
    result = {
        "text": getattr(output, "text", "") if output else "",
        "images": saved,
        "chat_id": output.metadata[0] if output and output.metadata else None,
        "account_source": getattr(args, "_account_source", None),
        "account_profile": getattr(args, "_account_profile", None),
        "account_emails": getattr(args, "_account_emails", []),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if result["text"]:
        print(result["text"])
    if saved:
        print("\nSaved images:")
        for item in saved:
            print(f"  {item['path']} ({item['type']})")
    else:
        print("No generated images were returned.")
    if result["chat_id"]:
        print(f"\nChat ID: {result['chat_id']}")
    if result["account_source"]:
        emails = ", ".join(result["account_emails"]) if result["account_emails"] else "-"
        print(f"Account: {result['account_source']} | {result['account_profile'] or '-'} | {emails}")


async def run_image_with_cookies(args: argparse.Namespace, json_cookies: dict[str, str], cookie_path: str | None) -> int:
    set_log_level("DEBUG" if args.verbose else "WARNING")
    client = make_client(args, json_cookies)
    try:
        await client.init(
            timeout=args.request_timeout,
            auto_refresh=not args.no_auto_refresh,
            refresh_interval=args.refresh_interval,
            watchdog_timeout=args.watchdog_timeout,
            verbose=args.verbose,
        )
    except AuthError as exc:
        await client.close()
        raise exc
    try:
        files = args.image or None
        if args.stream:
            output = None
            async for output in client.generate_content_stream(
                args.prompt,
                files=files,
                model=args.model,
                temporary=args.temporary,
                pro_image=True,
            ):
                if output.text_delta and not args.json:
                    print(output.text_delta, end="", flush=True)
            if output and not args.json and output.text_delta:
                print()
        else:
            output = await client.generate_content(
                args.prompt,
                files=files,
                model=args.model,
                temporary=args.temporary,
                pro_image=True,
            )
        saved = await save_images(output, args)
        print_result(output, saved, args)
        return 0
    finally:
        await cleanup(client, args, json_cookies, cookie_path)


async def run_image(args: argparse.Namespace) -> int:
    cookie_path = resolve_cookie_path(args)
    if should_use_account_pool(args):
        candidates = await collect_chrome_account_candidates(args)
        if candidates:
            failures: list[str] = []
            for candidate in candidates:
                args._account_source = candidate["source"]
                args._account_profile = candidate.get("profile_name", "")
                args._account_emails = candidate.get("emails", [])
                save_cookie_dict(
                    cookie_path,
                    candidate["cookies"],
                    source=f"browser:{candidate['source']}",
                    extra_meta={
                        "account_status": candidate["account_status"],
                        "profile_name": candidate.get("profile_name", ""),
                        "emails": candidate.get("emails", []),
                    },
                )
                try:
                    return await run_image_with_cookies(args, candidate["cookies"], cookie_path)
                except (AuthError, GeminiError, RuntimeError, TimeoutError) as exc:
                    failures.append(f"{candidate['source']}: {exc}")
                    if args.verbose:
                        logger.warning(f"Account candidate failed: {failures[-1]}")
                    continue
            raise SystemExit("All Gemini account candidates failed:\n" + "\n".join(failures))

    client, json_cookies, cookie_path = await init_client(args)
    args._account_source = None
    args._account_profile = None
    args._account_emails = []
    try:
        files = args.image or None
        if args.stream:
            output = None
            async for output in client.generate_content_stream(
                args.prompt,
                files=files,
                model=args.model,
                temporary=args.temporary,
                pro_image=True,
            ):
                if output.text_delta and not args.json:
                    print(output.text_delta, end="", flush=True)
            if output and not args.json and output.text_delta:
                print()
        else:
            output = await client.generate_content(
                args.prompt,
                files=files,
                model=args.model,
                temporary=args.temporary,
                pro_image=True,
            )
        saved = await save_images(output, args)
        print_result(output, saved, args)
        return 0
    finally:
        await cleanup(client, args, json_cookies, cookie_path)


async def run_models(args: argparse.Namespace) -> int:
    client, json_cookies, cookie_path = await init_client(args)
    try:
        models = client.list_models() or []
        if args.json:
            print(json.dumps([m.model_dump() for m in models], ensure_ascii=False, indent=2))
        else:
            for model in models:
                availability = "available" if getattr(model, "is_available", True) else "unavailable"
                print(f"{model.model_name or model.display_name} [{availability}] - {model.display_name}")
        return 0
    finally:
        await cleanup(client, args, json_cookies, cookie_path)


async def run_inspect(args: argparse.Namespace) -> int:
    client, json_cookies, cookie_path = await init_client(args)
    try:
        models = client.list_models() or []
        payload = {
            "account_status": getattr(client.account_status, "name", str(client.account_status)),
            "model_count": len(models),
            "models": [m.model_name or m.display_name for m in models],
            "cookie_path": cookie_path,
            "pro_image_forced": True,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else "\n".join(f"{k}: {v}" for k, v in payload.items()))
        return 0
    finally:
        await cleanup(client, args, json_cookies, cookie_path)


async def run_auth(args: argparse.Namespace) -> int:
    cookies, cookie_path = ensure_cookie_file(args)
    source = None
    result = {
        "cookie_path": cookie_path,
        "browser": args.browser,
        "source": source,
        "has_1psid": "__Secure-1PSID" in cookies,
        "has_1psidts": "__Secure-1PSIDTS" in cookies,
        "cookie_count": len(cookies),
        "verified": None,
        "account_status": None,
    }
    if not args.no_auth_verify:
        status = await verify_cookie_status(args, cookies)
        result["account_status"] = status
        result["verified"] = status == "AVAILABLE"

        should_scan_chrome = (
            not result["verified"]
            and args.browser in {"auto", "chrome"}
            and not args.browser_profile
            and not args.cookie_db
        )
        if should_scan_chrome:
            match = await find_verified_chrome_profile(args)
            if match:
                cookies, source, status, account = match
                save_cookie_dict(
                    cookie_path,
                    cookies,
                    source=f"browser:{source}",
                    extra_meta={
                        "account_status": status,
                        "profile_name": account.get("profile_name", ""),
                        "emails": account.get("emails", []),
                    },
                )
                result.update(
                    {
                        "source": source,
                        "profile_name": account.get("profile_name", ""),
                        "emails": account.get("emails", []),
                        "has_1psid": "__Secure-1PSID" in cookies,
                        "has_1psidts": "__Secure-1PSIDTS" in cookies,
                        "cookie_count": len(cookies),
                        "verified": True,
                        "account_status": status,
                    }
                )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Cookie file: {cookie_path}")
        print(f"Browser: {args.browser}")
        if result["source"]:
            print(f"Source: {result['source']}")
        if result.get("profile_name") or result.get("emails"):
            emails = ", ".join(result.get("emails") or []) or "-"
            print(f"Account: {result.get('profile_name') or '-'} | {emails}")
        print(f"__Secure-1PSID: {'yes' if result['has_1psid'] else 'no'}")
        print(f"__Secure-1PSIDTS: {'yes' if result['has_1psidts'] else 'no'}")
        print(f"Cookie count: {result['cookie_count']}")
        if result["verified"] is not None:
            print(f"Verified: {'yes' if result['verified'] else 'no'}")
            print(f"Account status: {result['account_status']}")
    return 0 if result["verified"] is not False else 2


async def run_accounts(args: argparse.Namespace) -> int:
    rows: list[dict[str, Any]] = []
    for profile_name, cookie_path in chrome_profile_cookie_paths():
        profile_info = read_chrome_profile_info(profile_name)
        row: dict[str, Any] = {
            **profile_info,
            "source": f"chrome:{profile_name}",
            "has_1psid": False,
            "has_1psidts": False,
            "cookie_count": 0,
            "account_status": "NO_COOKIES",
            "model_count": 0,
            "models": [],
        }
        try:
            cookies, _ = load_chrome_cookie_file(cookie_path, source=f"chrome:{profile_name}", verbose=args.verbose)
            row.update(
                {
                    "has_1psid": "__Secure-1PSID" in cookies,
                    "has_1psidts": "__Secure-1PSIDTS" in cookies,
                    "cookie_count": len(cookies),
                }
            )
            row.update(await inspect_cookie_account(args, cookies))
        except SystemExit as exc:
            row["account_status"] = f"IMPORT_ERROR: {exc}"
        rows.append(row)

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            emails = ", ".join(row["emails"]) if row["emails"] else "-"
            model_names = ", ".join(model["name"] for model in row["models"] if model.get("available")) or "-"
            print(
                f"{row['source']} | {row['profile_name'] or '-'} | {emails} | "
                f"{row['account_status']} | {model_names}"
            )
    return 0


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cookies-json", default=None, help="Gemini web cookies JSON path")
    parser.add_argument("--proxy", default=os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY"))
    parser.add_argument("--account-index", type=int, default=None)
    parser.add_argument("--model", default=Model.UNSPECIFIED.model_name)
    parser.add_argument("--request-timeout", type=float, default=300)
    parser.add_argument("--watchdog-timeout", type=float, default=120)
    parser.add_argument("--refresh-interval", type=float, default=600, help="Persistent cookie refresh interval in seconds")
    parser.add_argument("--no-auto-refresh", action="store_true", help="Disable background persistent cookie refresh")
    parser.add_argument("--keepalive-seconds", type=float, default=0, help="Keep the client alive after the command so background refresh can run")
    parser.add_argument("--refresh-browser-cookies", action="store_true", help="Re-import cookies from local browser before running")
    parser.add_argument("--browser", choices=sorted(SUPPORTED_BROWSERS), default="auto", help="Browser to import cookies from when needed")
    parser.add_argument("--browser-profile", default=None, help="Chrome profile directory name, for example Default or 'Profile 9'")
    parser.add_argument("--cookie-db", default=None, help="Direct Chrome cookie SQLite DB path for advanced troubleshooting")
    parser.add_argument("--no-account-failover", action="store_true", help="Disable automatic account pool selection and failover")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print JSON summary")


def add_image_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("prompt", help="Prompt/instruction")
    parser.add_argument("--image", action="append", default=[], help="Input/reference image. Repeatable for edit mode.")
    parser.add_argument("--output-dir", default="./outputs")
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--full-size", dest="full_size", action="store_true", default=True)
    parser.add_argument("--no-full-size", dest="full_size", action="store_false")
    parser.add_argument("--save-web-images", action="store_true")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--temporary", action="store_true", help="Do not save conversation to Gemini history")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone Gemini Nano Banana Pro image CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_generate = sub.add_parser("generate", help="Text-to-image with Nano Banana Pro")
    add_common(p_generate)
    add_image_args(p_generate)

    p_edit = sub.add_parser("edit", help="Image editing with Nano Banana Pro")
    add_common(p_edit)
    add_image_args(p_edit)

    p_models = sub.add_parser("models", help="List Gemini models available to the account")
    add_common(p_models)

    p_inspect = sub.add_parser("inspect", help="Inspect auth/account state")
    add_common(p_inspect)

    p_auth = sub.add_parser("auth", help="Import Gemini cookies from local browser into the persistent cookie file")
    add_common(p_auth)
    p_auth.add_argument("--no-auth-verify", action="store_true", help="Only import cookies; do not verify the Gemini session")

    p_accounts = sub.add_parser("accounts", help="Scan Chrome profiles and show Gemini account status/models")
    add_common(p_accounts)
    return parser


async def dispatch(args: argparse.Namespace) -> int:
    if args.command == "generate":
        args.image = []
        return await run_image(args)
    if args.command == "edit":
        if not args.image:
            raise SystemExit("edit requires at least one --image")
        return await run_image(args)
    if args.command == "models":
        return await run_models(args)
    if args.command == "inspect":
        return await run_inspect(args)
    if args.command == "auth":
        return await run_auth(args)
    if args.command == "accounts":
        return await run_accounts(args)
    raise SystemExit("Unknown command")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(dispatch(args))
    except GeminiError as exc:
        print(f"Gemini request failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
