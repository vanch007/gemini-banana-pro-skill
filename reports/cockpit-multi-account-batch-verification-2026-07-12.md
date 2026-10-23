# Cockpit Multi-account Batch Verification - 2026-07-12

Status: pass

## Automated Verification

- Python syntax check: pass
- Unit tests: 11/11 pass
- Distinct-account concurrent start: pass
- Failed-account task redistribution: pass
- Atomic status and attempt history: pass

## Live Verification

Command mode:

- `batch`
- `--auth-source cockpit`
- `--workers 4`
- `--account-tier pro`
- model `gemini-3.1-flash-image`

Two tasks were submitted together. The first two selected PRO accounts returned
HTTP 429 `RESOURCE_EXHAUSTED`. Both tasks were automatically redistributed to
two other PRO accounts and completed successfully.

| Task | Final result | Actual pixels | Final account |
| --- | --- | --- | --- |
| `probe_coral` | pass | 1024x1024 | `702b9ee0-****-****-****-************` |
| `probe_teal` | pass | 1024x1024 | `64b1e32b-****-****-****-************` |

The successful generation intervals overlapped, proving concurrent execution
on distinct accounts.

## Evidence

- Manifest:
  `./outputs/gemini_banana_pro_concurrency_probe_20260712/probe_manifest.json`
- Status:
  `./outputs/gemini_banana_pro_concurrency_probe_20260712/probe_status_4_accounts.json`
- Outputs:
  `./outputs/gemini_banana_pro_concurrency_probe_20260712/probe_coral/`
  and
  `./outputs/gemini_banana_pro_concurrency_probe_20260712/probe_teal/`

## Residual Risk

Concurrency cannot create quota. If every selected account is exhausted, tasks
end as `fail` with complete attempt evidence. Listing QA remains a separate
required gate after generation.
