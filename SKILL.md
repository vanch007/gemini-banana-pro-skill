---
name: gemini-banana-pro
description: Standalone Gemini Web Nano Banana Pro image generation and image editing skill. Uses vendored gemini_webapi code inside this skill, reads Gemini web cookies, and calls Gemini with pro_image=True for text-to-image and image-to-image editing. Does not depend on a local Gemini-API checkout.
---

# gemini-banana-pro

Standalone Nano Banana Pro image generation and image editing through Gemini Web.

This skill is self-contained: it vendors the required `gemini_webapi` runtime in
`vendor/gemini_webapi` and does not import `/Users/vanch/Gemini-API`.

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

```bash
python3 scripts/banana_pro.py inspect --cookies-json ./cookies.json
python3 scripts/banana_pro.py models --cookies-json ./cookies.json
python3 scripts/banana_pro.py auth --browser chrome --refresh-browser-cookies
python3 scripts/banana_pro.py accounts
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

## Parameters

Shared:

- `--cookies-json`
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

Edit mode:

- `--image` can be repeated for multi-image editing/reference input.

## Notes

- Nano Banana Pro is forced by passing `pro_image=True` in the vendored Gemini
  Web client.
- Persistent cookies are enabled by default with `auto_refresh=True`. Refreshed
  cookies are written back to the same cookie JSON unless `--no-persist` is set.
- Gemini feature availability still depends on the signed-in Google account,
  country, age eligibility, and plan.
- Image output is currently about 2K, not true 4K.
- Size, aspect ratio, style, and number of images are Gemini Web prompt-level
  controls, not stable public API fields in this reverse-engineered client.
