#!/usr/bin/env python3
"""Standalone Gemini Web Nano Banana Pro image CLI."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import sys
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))

try:
    import browser_cookie3 as bc3  # noqa: E402
    from curl_cffi import requests as http_requests  # noqa: E402
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
DEFAULT_COCKPIT_DIR = Path.home() / ".antigravity_cockpit"
COCKPIT_IMAGE_MODEL = "gemini-3.1-flash-image"
COCKPIT_CLIENT_KEY = "antigravity_enterprise"
COCKPIT_CLIENT_ID = os.getenv("ANTIGRAVITY_CLIENT_ID", "")
COCKPIT_CLIENT_SECRET = os.getenv("ANTIGRAVITY_CLIENT_SECRET", "")
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
COCKPIT_ENDPOINTS = [
    "https://daily-cloudcode-pa.sandbox.googleapis.com/v1internal",
    "https://daily-cloudcode-pa.googleapis.com/v1internal",
    "https://cloudcode-pa.googleapis.com/v1internal",
]
COCKPIT_VERSION = os.getenv("ANTIGRAVITY_VERSION", "4.1.31")
COCKPIT_USER_AGENT = os.getenv(
    "ANTIGRAVITY_USER_AGENT",
    (
        f"Antigravity/{COCKPIT_VERSION} "
        "(Macintosh; Intel Mac OS X 10_15_7) "
        "Chrome/132.0.6834.160 Electron/39.2.3"
    ),
)
COCKPIT_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "OFF"},
]
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
    "COMPASS",
    "__Secure-STRP",
    "AEC",
}


def cockpit_accounts_dir(args: argparse.Namespace) -> Path:
    root = Path(getattr(args, "cockpit_dir", None) or DEFAULT_COCKPIT_DIR).expanduser()
    return root / "accounts"


def load_cockpit_accounts(args: argparse.Namespace) -> list[dict[str, Any]]:
    accounts_dir = cockpit_accounts_dir(args)
    if not accounts_dir.exists():
        raise SystemExit(f"Cockpit account directory does not exist: {accounts_dir}")
    accounts: list[dict[str, Any]] = []
    for path in sorted(accounts_dir.glob("*.json")):
        try:
            account = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(account, dict):
            continue
        account["_path"] = str(path)
        accounts.append(account)
    return accounts


def cockpit_model_names(account: dict[str, Any]) -> list[str]:
    quota = account.get("quota") if isinstance(account.get("quota"), dict) else {}
    models = quota.get("models") if isinstance(quota, dict) else []
    names: list[str] = []
    for model in models if isinstance(models, list) else []:
        if isinstance(model, str):
            name = model
        elif isinstance(model, dict):
            name = model.get("model_id") or model.get("id") or model.get("name")
        else:
            name = None
        if isinstance(name, str) and name:
            names.append(name)
    return names


def cockpit_subscription_tier(account: dict[str, Any]) -> str:
    quota = account.get("quota") if isinstance(account.get("quota"), dict) else {}
    value = quota.get("subscription_tier") if isinstance(quota, dict) else None
    return str(value or "").strip().lower()


def cockpit_is_pro(account: dict[str, Any]) -> bool:
    tier = cockpit_subscription_tier(account)
    return tier == "g1-pro-tier" or ("pro" in tier and "free" not in tier)


def cockpit_current_account_id(args: argparse.Namespace) -> str | None:
    index_path = cockpit_accounts_dir(args).parent / "accounts.json"
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("current_account_id") if isinstance(payload, dict) else None
    return value if isinstance(value, str) and value else None


def cockpit_account_priority(
    account: dict[str, Any],
    current_account_id: str | None,
) -> tuple[int, int, str]:
    tier = cockpit_subscription_tier(account)
    is_pro = tier == "g1-pro-tier" or ("pro" in tier and "free" not in tier)
    is_current = bool(current_account_id and account.get("id") == current_account_id)
    return (
        0 if is_pro else 1,
        0 if is_current else 1,
        str(account.get("email") or account.get("id") or ""),
    )


def select_cockpit_accounts(args: argparse.Namespace) -> list[dict[str, Any]]:
    accounts = [
        account
        for account in load_cockpit_accounts(args)
        if not account.get("disabled") and not account.get("proxy_disabled")
    ]
    account_id = getattr(args, "cockpit_account_id", None)
    account_email = getattr(args, "cockpit_account_email", None)
    if account_id:
        accounts = [account for account in accounts if account.get("id") == account_id]
    if account_email:
        accounts = [
            account
            for account in accounts
            if str(account.get("email", "")).lower() == account_email.lower()
        ]
    if not accounts:
        selector = account_id or account_email or "enabled accounts"
        raise SystemExit(f"No Cockpit account matched: {selector}")
    capable = [account for account in accounts if COCKPIT_IMAGE_MODEL in cockpit_model_names(account)]
    selected = capable or accounts
    if account_id or account_email:
        return selected
    current_account_id = cockpit_current_account_id(args)
    return sorted(
        selected,
        key=lambda account: cockpit_account_priority(account, current_account_id),
    )


def resolve_cockpit_oauth_client(cockpit_dir: Path | None = None) -> tuple[str, str]:
    client_id = os.getenv("ANTIGRAVITY_CLIENT_ID") or os.getenv("COCKPIT_CLIENT_ID") or COCKPIT_CLIENT_ID
    client_secret = os.getenv("ANTIGRAVITY_CLIENT_SECRET") or os.getenv("COCKPIT_CLIENT_SECRET") or COCKPIT_CLIENT_SECRET
    if client_id and client_secret:
        return client_id, client_secret
    root = cockpit_dir or DEFAULT_COCKPIT_DIR
    oauth_file = root / "oauth_client.json"
    if oauth_file.exists():
        try:
            data = json.loads(oauth_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cid = data.get("client_id") or data.get("clientId") or ""
                csecret = data.get("client_secret") or data.get("clientSecret") or ""
                if cid and csecret:
                    return str(cid), str(csecret)
        except (OSError, json.JSONDecodeError):
            pass
    return client_id, client_secret


def cockpit_oauth_clients(preferred_key: str | None, cockpit_dir: Path | None = None) -> list[dict[str, str]]:
    clients: list[dict[str, str]] = []
    default_id, default_secret = resolve_cockpit_oauth_client(cockpit_dir)
    if default_id and default_secret:
        clients.append(
            {
                "key": COCKPIT_CLIENT_KEY,
                "client_id": default_id,
                "client_secret": default_secret,
            }
        )
    raw = os.getenv("ANTIGRAVITY_OAUTH_CLIENTS", "")
    for entry in raw.split(";"):
        parts = [part.strip() for part in entry.split("|")]
        if len(parts) < 3 or not all(parts[:3]):
            continue
        key, client_id, client_secret = parts[:3]
        clients = [client for client in clients if client["key"] != key.lower()]
        clients.append(
            {
                "key": key.lower(),
                "client_id": client_id,
                "client_secret": client_secret,
            }
        )
    wanted = [
        value
        for value in [
            (preferred_key or "").strip().lower(),
            os.getenv("ANTIGRAVITY_OAUTH_CLIENT_KEY", "").strip().lower(),
            COCKPIT_CLIENT_KEY,
        ]
        if value
    ]
    ordered: list[dict[str, str]] = []
    for key in wanted:
        ordered.extend(client for client in clients if client["key"] == key and client not in ordered)
    ordered.extend(client for client in clients if client not in ordered)
    return ordered


def refresh_cockpit_access_token(account: dict[str, Any], args: argparse.Namespace) -> str:
    token = account.get("token") if isinstance(account.get("token"), dict) else {}
    refresh_token = token.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise RuntimeError("account does not contain token.refresh_token")
    cockpit_dir = Path(getattr(args, "cockpit_dir", None) or DEFAULT_COCKPIT_DIR).expanduser()
    clients = cockpit_oauth_clients(token.get("oauth_client_key"), cockpit_dir=cockpit_dir)
    if not clients:
        raise RuntimeError(
            "No Antigravity OAuth client credentials configured. "
            "Set ANTIGRAVITY_CLIENT_ID and ANTIGRAVITY_CLIENT_SECRET environment variables, "
            "or configure ~/.antigravity_cockpit/oauth_client.json."
        )
    errors: list[str] = []
    for client in clients:
        response = http_requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            proxy=args.proxy,
            timeout=30,
            verify=not args.skip_verify,
        )
        if response.ok:
            payload = response.json()
            access_token = payload.get("access_token")
            if isinstance(access_token, str) and access_token:
                return access_token
        errors.append(f"{client['key']}: HTTP {response.status_code}")
    raise RuntimeError("OAuth refresh failed: " + ", ".join(errors))


def cockpit_headers(access_token: str) -> dict[str, str]:
    machine_source = os.getenv("ANTIGRAVITY_MACHINE_ID") or f"{os.uname().nodename}:{uuid.getnode()}"
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": COCKPIT_USER_AGENT,
        "x-client-name": "antigravity",
        "x-client-version": COCKPIT_VERSION,
        "x-machine-id": hashlib.sha256(machine_source.encode("utf-8")).hexdigest(),
        "x-vscode-sessionid": str(uuid.uuid4()),
    }


def fetch_cockpit_project_id(access_token: str, args: argparse.Namespace) -> str:
    response = http_requests.post(
        COCKPIT_ENDPOINTS[0] + ":loadCodeAssist",
        headers=cockpit_headers(access_token),
        json={"metadata": {"ideType": "ANTIGRAVITY"}},
        proxy=args.proxy,
        timeout=30,
        verify=not args.skip_verify,
    )
    response.raise_for_status()
    value = response.json().get("cloudaicompanionProject")
    if isinstance(value, dict):
        value = value.get("id")
    if not isinstance(value, str) or not value:
        raise RuntimeError("loadCodeAssist did not return cloudaicompanionProject")
    return value


def cockpit_aspect_ratio(value: str | None) -> str:
    if not value:
        return "1:1"
    if ":" in value:
        return value
    if "x" not in value.lower():
        return "1:1"
    try:
        width, height = (float(item) for item in value.lower().split("x", 1))
        ratio = width / height
    except (ValueError, ZeroDivisionError):
        return "1:1"
    targets = {
        "21:9": 21 / 9,
        "16:9": 16 / 9,
        "9:16": 9 / 16,
        "4:3": 4 / 3,
        "3:4": 3 / 4,
        "3:2": 3 / 2,
        "2:3": 2 / 3,
        "5:4": 5 / 4,
        "4:5": 4 / 5,
        "1:1": 1.0,
    }
    return min(targets, key=lambda name: abs(targets[name] - ratio))


def cockpit_image_size(args: argparse.Namespace) -> str | None:
    if args.image_size:
        return args.image_size.upper()
    return {
        "standard": "1K",
        "1k": "1K",
        "medium": "2K",
        "2k": "2K",
        "hd": "4K",
        "4k": "4K",
    }.get((args.quality or "").lower())


def cockpit_image_part(path_value: str) -> dict[str, Any]:
    path = Path(path_value).expanduser()
    if not path.exists():
        raise SystemExit(f"Image file does not exist: {path}")
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return {
        "inlineData": {
            "mimeType": mime_type,
            "data": base64.b64encode(path.read_bytes()).decode("ascii"),
        }
    }


def build_cockpit_body(args: argparse.Namespace, project_id: str) -> dict[str, Any]:
    parts = [{"text": args.prompt}]
    parts.extend(cockpit_image_part(path) for path in args.image)
    image_config = {"aspectRatio": cockpit_aspect_ratio(args.size)}
    image_size = cockpit_image_size(args)
    if image_size:
        image_config["imageSize"] = image_size
    return {
        "project": project_id,
        "requestId": f"image_gen/{int(datetime.now().timestamp() * 1000)}/{uuid.uuid4()}/12",
        "model": COCKPIT_IMAGE_MODEL,
        "userAgent": "antigravity",
        "requestType": "image_gen",
        "request": {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"candidateCount": 1, "imageConfig": image_config},
            "safetySettings": COCKPIT_SAFETY_SETTINGS,
        },
    }


def request_cockpit_image(access_token: str, body: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    last_error = "unknown error"
    for endpoint in COCKPIT_ENDPOINTS:
        response = http_requests.post(
            endpoint + ":generateContent",
            headers=cockpit_headers(access_token),
            json=body,
            proxy=args.proxy,
            timeout=args.request_timeout,
            verify=not args.skip_verify,
        )
        if response.ok:
            return response.json()
        last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        if response.status_code not in {404, 408, 429, 500, 502, 503, 504}:
            break
    raise RuntimeError(last_error)


def extract_cockpit_images(payload: dict[str, Any]) -> list[tuple[str, bytes]]:
    response = payload.get("response") if isinstance(payload.get("response"), dict) else payload
    candidates = response.get("candidates") if isinstance(response, dict) else []
    images: list[tuple[str, bytes]] = []
    for candidate in candidates if isinstance(candidates, list) else []:
        content = candidate.get("content") if isinstance(candidate, dict) else {}
        parts = content.get("parts") if isinstance(content, dict) else []
        for part in parts if isinstance(parts, list) else []:
            inline = part.get("inlineData") if isinstance(part, dict) else None
            if not isinstance(inline, dict) or not inline.get("data"):
                continue
            images.append(
                (
                    str(inline.get("mimeType") or "image/png"),
                    base64.b64decode(inline["data"]),
                )
            )
    return images


def cockpit_extension(mime_type: str) -> str:
    return {"image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(mime_type, ".png")
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
        status_name = getattr(client.account_status, "name", str(client.account_status))
        if getattr(client, "access_token", None):
            status_name = "AVAILABLE"
        return {
            "account_status": status_name,
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
    if args.auth_source == "cockpit":
        return await run_cockpit_image(args)

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


async def run_cockpit_image(args: argparse.Namespace) -> int:
    failures: list[str] = []
    accounts = select_cockpit_accounts(args)
    for account in accounts:
        email = str(account.get("email") or "-")
        account_id = str(account.get("id") or "-")
        try:
            result = await generate_cockpit_with_account(args, account)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print("Saved images:")
                for item in result["images"]:
                    print(f"  {item['path']} ({item['mime_type']})")
                print(f"Account: cockpit:{account_id} | {email}")
                print(f"Tier: {cockpit_subscription_tier(account) or '-'}")
                print(f"Model: {COCKPIT_IMAGE_MODEL}")
            return 0
        except Exception as exc:
            failures.append(f"{email} ({account_id}): {exc}")
            if args.no_account_failover:
                break
    raise SystemExit("All Cockpit account candidates failed:\n" + "\n".join(failures))


async def generate_cockpit_with_account(
    args: argparse.Namespace,
    account: dict[str, Any],
) -> dict[str, Any]:
    email = str(account.get("email") or "-")
    account_id = str(account.get("id") or "-")
    access_token = await asyncio.to_thread(refresh_cockpit_access_token, account, args)
    token = account.get("token") if isinstance(account.get("token"), dict) else {}
    project_id = token.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        project_id = await asyncio.to_thread(fetch_cockpit_project_id, access_token, args)
    body = build_cockpit_body(args, project_id)
    payload = await asyncio.to_thread(request_cockpit_image, access_token, body, args)
    images = extract_cockpit_images(payload)
    if not images:
        raise RuntimeError("generateContent returned no inline image")

    out_dir = Path(args.output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.prefix or "banana_pro_cockpit"
    saved: list[dict[str, Any]] = []
    for index, (mime_type, image_bytes) in enumerate(images, start=1):
        path = out_dir / f"{prefix}_generated_{index}{cockpit_extension(mime_type)}"
        path.write_bytes(image_bytes)
        saved.append(
            {
                "path": str(path),
                "type": "generated",
                "mime_type": mime_type,
            }
        )
    return {
        "text": "",
        "images": saved,
        "chat_id": None,
        "auth_source": "cockpit",
        "account_source": f"cockpit:{account_id}",
        "account_profile": "",
        "account_emails": [email] if email != "-" else [],
        "account_tier": cockpit_subscription_tier(account) or None,
        "model": COCKPIT_IMAGE_MODEL,
    }


def load_batch_manifest(path_value: str | Path) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    path = Path(path_value).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"Could not read batch manifest: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid batch manifest JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("Batch manifest root must be a JSON object.")
    defaults = payload.get("defaults") or {}
    tasks = payload.get("tasks")
    if not isinstance(defaults, dict):
        raise SystemExit("Batch manifest 'defaults' must be an object.")
    if not isinstance(tasks, list) or not tasks:
        raise SystemExit("Batch manifest requires a non-empty 'tasks' array.")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise SystemExit(f"Batch task {index} must be an object.")
        task_id = task.get("id")
        prompt = task.get("prompt")
        if not isinstance(task_id, str) or not task_id.strip():
            raise SystemExit(f"Batch task {index} requires a non-empty string 'id'.")
        if task_id in seen_ids:
            raise SystemExit(f"Duplicate batch task id: {task_id}")
        if not isinstance(prompt, str) or not prompt.strip():
            raise SystemExit(f"Batch task {task_id} requires a non-empty string 'prompt'.")
        images = task.get("images", task.get("image", []))
        if isinstance(images, str):
            images = [images]
        if not isinstance(images, list) or not all(isinstance(item, str) for item in images):
            raise SystemExit(f"Batch task {task_id} 'images' must be a string array.")
        seen_ids.add(task_id)
        normalized.append({**task, "id": task_id.strip(), "prompt": prompt, "images": images})
    return path, defaults, normalized


def resolve_manifest_path(value: str, manifest_dir: Path) -> str:
    path = Path(value).expanduser()
    return str(path if path.is_absolute() else (manifest_dir / path).resolve())


def build_batch_task_args(
    batch_args: argparse.Namespace,
    manifest_path: Path,
    defaults: dict[str, Any],
    task: dict[str, Any],
) -> argparse.Namespace:
    task_args = argparse.Namespace(**vars(batch_args))
    manifest_dir = manifest_path.parent
    task_args.prompt = task["prompt"]
    task_args.image = [
        resolve_manifest_path(value, manifest_dir)
        for value in task.get("images", [])
    ]
    output_dir = task.get("output_dir", defaults.get("output_dir", "./outputs"))
    task_args.output_dir = resolve_manifest_path(str(output_dir), manifest_dir)
    task_args.prefix = str(task.get("prefix", defaults.get("prefix", task["id"])))
    task_args.size = task.get("size", defaults.get("size"))
    task_args.quality = task.get("quality", defaults.get("quality"))
    task_args.image_size = task.get("image_size", defaults.get("image_size"))
    return task_args


def batch_existing_images(task_args: argparse.Namespace) -> list[str]:
    out_dir = Path(task_args.output_dir).expanduser()
    if not out_dir.exists():
        return []
    prefix = task_args.prefix or "banana_pro_cockpit"
    return sorted(str(path) for path in out_dir.glob(f"{prefix}_generated_*.*") if path.is_file())


def write_batch_status(
    status_path: Path,
    manifest_path: Path,
    accounts: list[dict[str, Any]],
    results: dict[str, dict[str, Any]],
) -> None:
    counts = {"pass": 0, "fail": 0, "skipped": 0, "pending": 0}
    for result in results.values():
        status = result.get("status", "pending")
        counts[status if status in counts else "pending"] += 1
    payload = {
        "manifest": str(manifest_path),
        "updated_at": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "model": COCKPIT_IMAGE_MODEL,
        "accounts": [
            {
                "id": account.get("id"),
                "email": account.get("email"),
                "tier": cockpit_subscription_tier(account),
            }
            for account in accounts
        ],
        "counts": counts,
        "tasks": [results[key] for key in sorted(results)],
    }
    status_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = status_path.with_suffix(status_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(status_path)


async def run_cockpit_batch(args: argparse.Namespace) -> int:
    if args.auth_source != "cockpit":
        raise SystemExit("batch currently requires --auth-source cockpit")
    manifest_path, defaults, tasks = load_batch_manifest(args.manifest)
    accounts = select_cockpit_accounts(args)
    if args.account_tier == "pro":
        accounts = [account for account in accounts if cockpit_is_pro(account)]
        if not accounts:
            raise SystemExit("No enabled image-capable Cockpit PRO accounts are available.")
    worker_count = min(args.workers or len(accounts), len(accounts))
    accounts = accounts[:worker_count]
    status_path = (
        Path(args.status_file).expanduser().resolve()
        if args.status_file
        else manifest_path.with_name(manifest_path.stem + "_status.json")
    )
    results: dict[str, dict[str, Any]] = {}
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    for task in tasks:
        task_args = build_batch_task_args(args, manifest_path, defaults, task)
        existing = batch_existing_images(task_args) if args.resume else []
        if existing:
            results[task["id"]] = {
                "id": task["id"],
                "status": "skipped",
                "reason": "existing_output",
                "images": existing,
                "output_dir": task_args.output_dir,
            }
            continue
        results[task["id"]] = {
            "id": task["id"],
            "status": "pending",
            "output_dir": task_args.output_dir,
            "failed_accounts": [],
            "attempts": [],
        }
        queue.put_nowait(
            {
                "task": task,
                "args": task_args,
                "failed_accounts": set(),
            }
        )
    write_batch_status(status_path, manifest_path, accounts, results)

    async def worker(account: dict[str, Any]) -> None:
        account_id = str(account.get("id") or "-")
        email = str(account.get("email") or "-")
        while True:
            state = await queue.get()
            if state is None:
                queue.task_done()
                return
            task = state["task"]
            task_id = task["id"]
            failed_accounts: set[str] = state["failed_accounts"]
            if account_id in failed_accounts:
                queue.put_nowait(state)
                queue.task_done()
                await asyncio.sleep(0.05)
                continue
            started_at = datetime.now(tz=timezone.utc)
            try:
                result = await generate_cockpit_with_account(state["args"], account)
                attempt = {
                    "account_id": account_id,
                    "account_email": email,
                    "started_at": started_at.isoformat().replace("+00:00", "Z"),
                    "finished_at": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                    "status": "pass",
                }
                results[task_id] = {
                    "id": task_id,
                    "status": "pass",
                    "account_id": account_id,
                    "account_email": email,
                    "account_tier": cockpit_subscription_tier(account),
                    "started_at": attempt["started_at"],
                    "finished_at": attempt["finished_at"],
                    "output_dir": state["args"].output_dir,
                    "images": result["images"],
                    "attempts": [*results[task_id].get("attempts", []), attempt],
                }
            except Exception as exc:
                failed_accounts.add(account_id)
                attempt = {
                    "account_id": account_id,
                    "account_email": email,
                    "started_at": started_at.isoformat().replace("+00:00", "Z"),
                    "finished_at": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                    "status": "fail",
                    "error": f"{type(exc).__name__}: {exc}",
                }
                attempts = [*results[task_id].get("attempts", []), attempt]
                if len(failed_accounts) < len(accounts):
                    results[task_id] = {
                        "id": task_id,
                        "status": "pending",
                        "output_dir": state["args"].output_dir,
                        "failed_accounts": sorted(failed_accounts),
                        "last_error": attempt["error"],
                        "attempts": attempts,
                    }
                    queue.put_nowait(state)
                else:
                    results[task_id] = {
                        "id": task_id,
                        "status": "fail",
                        "output_dir": state["args"].output_dir,
                        "failed_accounts": sorted(failed_accounts),
                        "error": attempt["error"],
                        "attempts": attempts,
                    }
            finally:
                write_batch_status(status_path, manifest_path, accounts, results)
                queue.task_done()

    workers = [asyncio.create_task(worker(account)) for account in accounts]
    await queue.join()
    for _ in workers:
        queue.put_nowait(None)
    await queue.join()
    await asyncio.gather(*workers)
    write_batch_status(status_path, manifest_path, accounts, results)
    summary = {
        "manifest": str(manifest_path),
        "status_file": str(status_path),
        "workers": len(accounts),
        "accounts": [
            {
                "id": account.get("id"),
                "email": account.get("email"),
                "tier": cockpit_subscription_tier(account),
            }
            for account in accounts
        ],
        "counts": {
            status: sum(1 for result in results.values() if result.get("status") == status)
            for status in ["pass", "fail", "skipped", "pending"]
        },
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"Batch manifest: {manifest_path}")
        print(f"Status file: {status_path}")
        print(f"Workers: {len(accounts)}")
        print("Counts: " + ", ".join(f"{key}={value}" for key, value in summary["counts"].items()))
    return 0 if summary["counts"]["fail"] == 0 and summary["counts"]["pending"] == 0 else 1


async def run_models(args: argparse.Namespace) -> int:
    if args.auth_source == "cockpit":
        rows = [
            {
                "id": account.get("id"),
                "email": account.get("email"),
                "models": cockpit_model_names(account),
                "subscription_tier": cockpit_subscription_tier(account),
            }
            for account in select_cockpit_accounts(args)
        ]
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for row in rows:
                print(f"cockpit:{row['id']} | {row['email']} | {', '.join(row['models']) or '-'}")
        return 0

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
    if args.auth_source == "cockpit":
        rows = [
            {
                "id": account.get("id"),
                "email": account.get("email"),
                "disabled": bool(account.get("disabled")),
                "has_refresh_token": bool(
                    isinstance(account.get("token"), dict)
                    and account["token"].get("refresh_token")
                ),
                "image_model_available": COCKPIT_IMAGE_MODEL in cockpit_model_names(account),
                "models": cockpit_model_names(account),
                "subscription_tier": cockpit_subscription_tier(account),
            }
            for account in select_cockpit_accounts(args)
        ]
        payload = {
            "auth_source": "cockpit",
            "accounts_dir": str(cockpit_accounts_dir(args)),
            "account_count": len(rows),
            "image_model": COCKPIT_IMAGE_MODEL,
            "accounts": rows,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

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
    if args.auth_source == "cockpit":
        accounts = select_cockpit_accounts(args)
        payload = {
            "auth_source": "cockpit",
            "accounts_dir": str(cockpit_accounts_dir(args)),
            "account_count": len(accounts),
            "accounts": [
                {
                    "id": account.get("id"),
                    "email": account.get("email"),
                    "has_refresh_token": bool(
                        isinstance(account.get("token"), dict)
                        and account["token"].get("refresh_token")
                    ),
                    "image_model_available": COCKPIT_IMAGE_MODEL in cockpit_model_names(account),
                    "subscription_tier": cockpit_subscription_tier(account),
                }
                for account in accounts
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

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
    if args.auth_source == "cockpit":
        rows = [
            {
                "source": f"cockpit:{account.get('id')}",
                "email": account.get("email"),
                "disabled": bool(account.get("disabled")),
                "models": cockpit_model_names(account),
                "image_model_available": COCKPIT_IMAGE_MODEL in cockpit_model_names(account),
                "subscription_tier": cockpit_subscription_tier(account),
            }
            for account in load_cockpit_accounts(args)
        ]
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for row in rows:
                status = "image-ready" if row["image_model_available"] else "image-model-missing"
                print(f"{row['source']} | {row['email']} | {status}")
        return 0

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
    parser.add_argument(
        "--auth-source",
        choices=["web", "cockpit"],
        default="web",
        help="Authentication/backend source: Gemini Web cookies or Cockpit Antigravity OAuth",
    )
    parser.add_argument("--cookies-json", default=None, help="Gemini web cookies JSON path")
    parser.add_argument(
        "--cockpit-dir",
        default=None,
        help="Cockpit data directory, defaults to ~/.antigravity_cockpit",
    )
    parser.add_argument("--cockpit-account-id", default=None, help="Select a Cockpit Antigravity account by id")
    parser.add_argument("--cockpit-account-email", default=None, help="Select a Cockpit Antigravity account by email")
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
    parser.add_argument("--size", default=None, help='Cockpit aspect ratio or dimensions, e.g. "16:9" or "1920x1080"')
    parser.add_argument(
        "--quality",
        choices=["standard", "1k", "medium", "2k", "hd", "4k"],
        default=None,
        help="Cockpit image quality shortcut",
    )
    parser.add_argument(
        "--image-size",
        choices=["1K", "2K", "4K", "1k", "2k", "4k"],
        default=None,
        help="Cockpit direct image size override",
    )


def add_batch_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", required=True, help="JSON manifest containing defaults and tasks")
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Concurrent workers/accounts. Default: all selected accounts up to task count.",
    )
    parser.add_argument(
        "--account-tier",
        choices=["pro", "all"],
        default="pro",
        help="Use PRO accounts only by default, or all enabled image-capable accounts.",
    )
    parser.add_argument("--status-file", default=None, help="Batch status JSON output path")
    parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.set_defaults(
        prompt="",
        image=[],
        output_dir="./outputs",
        prefix=None,
        size=None,
        quality=None,
        image_size=None,
        full_size=True,
        save_web_images=False,
        stream=False,
        temporary=False,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone Gemini Nano Banana Pro image CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_generate = sub.add_parser("generate", help="Text-to-image with Nano Banana Pro")
    add_common(p_generate)
    add_image_args(p_generate)

    p_edit = sub.add_parser("edit", help="Image editing with Nano Banana Pro")
    add_common(p_edit)
    add_image_args(p_edit)

    p_batch = sub.add_parser("batch", help="Run a JSON image-task manifest across Cockpit accounts concurrently")
    add_common(p_batch)
    add_batch_args(p_batch)

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
    if args.command == "batch":
        return await run_cockpit_batch(args)
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
