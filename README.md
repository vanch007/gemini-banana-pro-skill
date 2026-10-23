# gemini-banana-pro

Standalone Gemini image CLI for generation and editing through either Gemini
Web cookies or Cockpit Tools Antigravity accounts.

This project is self-contained. It vendors the required `gemini_webapi` runtime
under `vendor/gemini_webapi`, so it does not depend on a local `Gemini-API`
checkout.

## Cockpit Tools Authentication

Cockpit Tools Antigravity accounts can be used directly without converting
their OAuth tokens into Gemini Web cookies:

```bash
python3 scripts/banana_pro.py generate \
  "A premium red lantern product photo on a dark wooden table" \
  --auth-source cockpit \
  --size 16:9 \
  --image-size 2K \
  --output-dir ./outputs
```

The CLI reads `~/.antigravity_cockpit/accounts`, refreshes the selected Google
OAuth token in memory, and calls Antigravity's image route with
`gemini-3.1-flash-image`. It does not modify Cockpit account files.

Use `--cockpit-account-email <email>` or `--cockpit-account-id <id>` to select
one account. Otherwise the current Cockpit PRO account is preferred, followed
by other PRO accounts and then FREE accounts.

## Multi-account Batch

Run a JSON task manifest across multiple Cockpit accounts:

```bash
python3 scripts/banana_pro.py batch \
  --auth-source cockpit \
  --manifest ./listing_batch.json \
  --workers 4 \
  --account-tier pro \
  --status-file ./listing_batch_status.json
```

Each worker is pinned to one account. Tasks that fail on one account are
requeued for another selected account. Existing prefixed outputs are skipped
when resume mode is enabled. The atomic status JSON retains every account
attempt, including quota failures and the account that ultimately produced the
image.

## Output Resolution

Gemini Web / Nano Banana Pro currently returns generated and edited images at
about 2K resolution in this CLI. In local testing, a 4K 16:9 input image
returned a `2752 x 1536` PNG. This skill can accept 4K source images, but it
cannot force true 4K output through the current Gemini Web image path.

If you need a final 4K asset, generate/edit with this skill first, then upscale
the saved PNG with a separate upscaler.

## Install

```bash
python3 -m pip install -r requirements.txt
```

## Authentication

This uses Gemini web cookies, not a Google AI Studio API key.

Cookie source priority:

1. `--cookies-json`
2. `GEMINI_COOKIES_JSON`
3. `./cookies.json` in this skill directory
4. local browser cookies from an already logged-in Gemini session
5. `GEMINI_SECURE_1PSID` and optional `GEMINI_SECURE_1PSIDTS`

After logging in to <https://gemini.google.com> in your browser, run:

```bash
python3 scripts/banana_pro.py auth --browser chrome --refresh-browser-cookies
```

Use the browser where Gemini is already signed in. Supported values include
`auto`, `chrome`, `edge`, `safari`, `arc`, `brave`, and `firefox`.

The skill will save a local `cookies.json`, verify the Gemini session, and keep
the cookie file refreshed after use. Use `--no-auth-verify` when you only want
to import browser cookies without making a Gemini request.

Example cookie file:

```json
{
  "cookies": {
    "__Secure-1PSID": "...",
    "__Secure-1PSIDTS": "..."
  }
}
```

Do not commit cookie files.

## Generate Image

```bash
python3 scripts/banana_pro.py generate \
  "Generate a cinematic product photo of a red lantern on a dark wooden table" \
  --cookies-json ./cookies.json \
  --output-dir ./outputs
```

## Edit Image

```bash
python3 scripts/banana_pro.py edit \
  "Change the background to a clean white studio backdrop" \
  --image ./input.png \
  --cookies-json ./cookies.json \
  --output-dir ./outputs
```

Use repeated `--image` flags for multi-image reference editing.

## Inspect Account

```bash
python3 scripts/banana_pro.py inspect --cookies-json ./cookies.json
python3 scripts/banana_pro.py models --cookies-json ./cookies.json
python3 scripts/banana_pro.py accounts
```

`accounts` scans local Chrome profiles and reports profile email, Gemini account
status, and available models. The CLI does not infer or rank account tiers; image
commands report the actual profile and email used.

## Useful Parameters

- `--model`: Gemini model name, defaults to `unspecified`.
- `--account-index`: Google account index.
- `--proxy`: HTTP/S proxy.
- `--request-timeout`: per-request timeout.
- `--watchdog-timeout`: stream watchdog timeout.
- `--refresh-interval`: persistent cookie refresh interval, defaults to `600`.
- `--no-auto-refresh`: disable background persistent cookie refresh.
- `--keepalive-seconds`: keep the process alive after a command so background refresh can run.
- `--refresh-browser-cookies`: re-import cookies from your browser before running.
- `--browser`: browser source for automatic cookie import.
- `--browser-profile`: explicit Chrome profile directory, for example `Profile 9`.
- `--no-account-failover`: disable automatic Chrome profile fallback.
- `--skip-verify`: skip TLS verification.
- `--no-persist`: do not write refreshed cookies back to the cookie file.
- `--output-dir`: image output directory.
- `--prefix`: output filename prefix.
- `--full-size / --no-full-size`: download full-size generated image when possible.
- `--save-web-images`: save web image results too.
- `--json`: print machine-readable result summary.

## Notes

Nano Banana Pro is selected by forcing the Gemini Web `pro_image=True` request
path. Persistent cookies are enabled by default and refreshed cookies are written
back to the same cookie file unless `--no-persist` is set. Availability still
depends on the signed-in Google account and region.
Image output is currently about 2K, not true 4K.
Aspect ratio, style, and image count should be expressed in the prompt because
Gemini Web does not expose stable public structured fields for those controls in
this reverse-engineered client.
