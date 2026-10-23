# Cockpit Backend Verification - 2026-07-11

Status: pass

Backend:

- Auth source: Cockpit Tools Antigravity OAuth
- Account selection: default, no explicit account selector
- Selected tier: `g1-pro-tier`
- Model: `gemini-3.1-flash-image`

## Account Routing

The default account order was verified as:

1. Current Cockpit PRO account
2. Other enabled PRO accounts
3. Enabled FREE accounts

All live requests in this matrix selected the current PRO account.

## Live Results

| Operation | Requested ratio | Requested size | Actual pixels | Result |
| --- | --- | --- | --- | --- |
| Edit | 4:5 | 1K | 928x1152 | pass |
| Generate | 16:9 | 1K | 1376x768 | pass |
| Generate | 9:16 | 1K | 768x1376 | pass |
| Generate | 4:5 | 2K | 1856x2304 | pass |
| Generate | 21:9 | 2K | 3168x1344 | pass |

The edit test used a red ceramic cube reference and requested a glossy cobalt
blue version on a pale gray studio background. The result preserved the object
shape and changed the requested color and background.

## Model Compatibility

`gemini-3-pro-image` was tested directly with the current Cockpit PRO account.
The upstream Antigravity endpoint returned HTTP `404 NOT_FOUND` with
`Requested entity was not found`.

The current Cockpit model catalog and all six account quota records expose
`gemini-3.1-flash-image`, but do not expose `gemini-3-pro-image`. Treat
`gemini-3-pro-image` as unavailable/deprecated for this backend.

## Artifacts

Temporary validation outputs:

- `/tmp/gemini-banana-pro-cockpit-matrix/edit/edit_4x5_generated_1.jpg`
- `/tmp/gemini-banana-pro-cockpit-matrix/wide_16x9/wide_16x9_generated_1.jpg`
- `/tmp/gemini-banana-pro-cockpit-matrix/portrait_9x16/portrait_9x16_generated_1.jpg`
- `/tmp/gemini-banana-pro-cockpit-matrix/product_4x5/product_4x5_generated_1.jpg`
- `/tmp/gemini-banana-pro-cockpit-matrix/ultrawide_21x9/ultrawide_21x9_generated_1.jpg`

## Residual Risk

The Cockpit backend depends on Google's non-public Antigravity `v1internal`
request contract. Upstream endpoint, OAuth client, model, or payload changes may
require an adapter update.
