---
name: gemini-banana-pro
description: Standalone Gemini image generation and editing skill with two explicit backends: Gemini Web Nano Banana Pro via web cookies, or Cockpit Tools Antigravity accounts via Google OAuth and gemini-3.1-flash-image. Does not depend on a local Gemini-API checkout.
---

# gemini-banana-pro

Standalone Gemini image generation and image editing with two authentication
backends:

- `web` (default): Gemini Web cookies and the vendored `gemini_webapi` runtime.
- `cockpit`: Cockpit Tools Antigravity OAuth accounts from
  `~/.antigravity_cockpit/accounts`.

The skill does not import a local `Gemini-API` checkout or another local skill.

## Resolution Limit

This skill can accept 4K input images, but Gemini Web / Nano Banana Pro currently
returns generated and edited images at about 2K resolution through this CLI. It
cannot force true 4K output; use a separate upscaler when a final 4K asset is
required.

## Commands

```bash
python3 scripts/banana_pro.py generate \
  "Generate a cinematic product photo of a red lantern on a dark wooden table" \
  --cookies-json ./cookies.json \
  --output-dir ./outputs
```

```bash
python3 scripts/banana_pro.py edit \
  "Change the background to a clean white studio backdrop" \
  --image ./input.png \
  --cookies-json ./cookies.json \
  --output-dir ./outputs
```

Cockpit Tools account authorization:

```bash
python3 scripts/banana_pro.py generate \
  "Generate a cinematic product photo of a red lantern on a dark wooden table" \
  --auth-source cockpit \
  --size 16:9 \
  --image-size 2K \
  --output-dir ./outputs
```

```bash
python3 scripts/banana_pro.py edit \
  "Keep the product unchanged and replace the background with a white studio" \
  --auth-source cockpit \
  --image ./input.png \
  --size 4:5 \
  --image-size 2K \
  --output-dir ./outputs
```

Batch multiple Listing tasks across Cockpit accounts:

```bash
python3 scripts/banana_pro.py batch \
  --auth-source cockpit \
  --manifest ./listing_batch.json \
  --workers 4 \
  --account-tier pro \
  --status-file ./listing_batch_status.json
```

Manifest:

```json
{
  "defaults": {
    "size": "1:1",
    "image_size": "2K",
    "output_dir": "./outputs"
  },
  "tasks": [
    {
      "id": "main_01",
      "prompt": "Create one finished Listing image...",
      "images": ["./source/main.jpg"],
      "output_dir": "./outputs/main_01",
      "prefix": "main_01"
    }
  ]
}
```

`batch` uses one worker per selected Cockpit account. PRO accounts are used by
default; tasks are redistributed to another selected account when an account
fails. The status JSON records each task, account, output path, and failure.
Each task also records an `attempts` history so quota failures and successful
cross-account retries remain auditable.
`--resume` is enabled by default and skips tasks whose prefixed output already
exists.

```bash
python3 scripts/banana_pro.py inspect --cookies-json ./cookies.json
python3 scripts/banana_pro.py models --cookies-json ./cookies.json
python3 scripts/banana_pro.py auth --browser chrome --refresh-browser-cookies
python3 scripts/banana_pro.py accounts
python3 scripts/banana_pro.py accounts --auth-source cockpit
python3 scripts/banana_pro.py inspect --auth-source cockpit
```

## Auth

Uses Gemini web cookies, not a Google AI Studio API key.

Auth priority:

1. `--cookies-json`
2. `GEMINI_COOKIES_JSON`
3. `./cookies.json` in this skill directory
4. local browser cookies from an already logged-in Gemini session
5. `GEMINI_SECURE_1PSID` and optional `GEMINI_SECURE_1PSIDTS`

Cookie JSON supports flat `{name: value}`, `{"cookies": {...}}`, Chrome-export
lists, or `{"cookies": [{ "name": "...", "value": "..." }]}`.

Run `python3 scripts/banana_pro.py auth --browser chrome --refresh-browser-cookies`
once after logging in to `https://gemini.google.com` in that browser. Replace
`chrome` with `edge`, `safari`, `arc`, `brave`, or `firefox` when needed.

The `auth` command imports browser cookies, verifies the Gemini session, and
then the skill maintains the cookie file with persistent background refresh. Use
`--no-auth-verify` only when you want to import cookies without a network check.

Use `accounts` to scan local Chrome profiles and show each profile's Gemini
account status and available models. Do not infer or rank account tiers; image
commands report the actual profile and email used.

### Cockpit Tools Auth

Use `--auth-source cockpit` to read Antigravity accounts managed by Cockpit
Tools. This backend:

- reads account records from `~/.antigravity_cockpit/accounts`;
- uses the stored Google OAuth refresh token only in memory;
- refreshes a short-lived access token through Google's OAuth endpoint;
- calls the Antigravity `v1internal` image route with
  `gemini-3.1-flash-image`;
- does not copy Cockpit refresh tokens into this skill or modify Cockpit files.

Select an account with `--cockpit-account-id` or
`--cockpit-account-email`. Without a selector, enabled image-capable accounts
are ordered by subscription tier: the current Cockpit PRO account first, then
other PRO accounts, then FREE accounts. Use `--no-account-failover` to disable
fallback after the first selected account.

Cockpit OAuth tokens are not Gemini Web cookies and cannot be passed to the
vendored `gemini_webapi` client. The skill therefore keeps the Web and Cockpit
backends separate behind the explicit `--auth-source` switch.

## Parameters

Shared:

- `--cookies-json`
- `--auth-source web|cockpit`
- `--cockpit-dir`
- `--cockpit-account-id`
- `--cockpit-account-email`
- `--model`
- `--account-index`
- `--proxy`
- `--request-timeout`
- `--watchdog-timeout`
- `--refresh-interval`
- `--no-auto-refresh`
- `--keepalive-seconds`
- `--refresh-browser-cookies`
- `--browser`
- `--browser-profile`
- `--no-account-failover`
- `--skip-verify`
- `--no-persist`
- `--verbose`

Image output:

- `--output-dir`
- `--prefix`
- `--full-size / --no-full-size`
- `--save-web-images`
- `--json`
- `--size` (Cockpit backend)
- `--quality` (Cockpit backend)
- `--image-size` (Cockpit backend)

Batch:

- `--manifest`
- `--workers`
- `--account-tier pro|all`
- `--status-file`
- `--resume / --no-resume`

Edit mode:

- `--image` can be repeated for multi-image editing/reference input.

## Notes

- Nano Banana Pro is forced by passing `pro_image=True` in the vendored Gemini
  Web client.
- Cockpit mode uses `gemini-3.1-flash-image` through Antigravity OAuth and does
  not use `pro_image=True`.
- Persistent cookies are enabled by default with `auto_refresh=True`. Refreshed
  cookies are written back to the same cookie JSON unless `--no-persist` is set.
- Gemini feature availability still depends on the signed-in Google account,
  country, age eligibility, and plan.
- Image output is currently about 2K, not true 4K.
- Cockpit accepts `1K`, `2K`, and `4K` image-size requests, but actual output
  dimensions and availability remain controlled by the upstream account and
  model.
- Verified Cockpit examples on 2026-07-11: `16:9 1K` returned `1376x768`,
  `9:16 1K` returned `768x1376`, `4:5 2K` returned `1856x2304`, and
  `21:9 2K` returned `3168x1344`. See
  `reports/cockpit-verification-2026-07-11.md`.
- Size, aspect ratio, style, and number of images are Gemini Web prompt-level
  controls, not stable public API fields in this reverse-engineered client.
