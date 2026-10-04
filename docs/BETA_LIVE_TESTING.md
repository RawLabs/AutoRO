# AutoRO Communication Layer 1.3.0-beta.1 Live Testing Guide

This Beta is intended for supervised use by an advisor. Review every generated document before sharing it with a customer. Mitchell remains the source of truth for job scope, labour, parts, quantities, and pricing.

## Start and confirm the release

1. Launch AutoRO with the supported Windows or Linux launcher.
2. Keep the AutoRO server and Qwen model windows open.
3. Confirm the footer reads `AutoRO 1.3.0-beta.1`.
4. Confirm the dashboard and Estimate Conversion status show Ready or Online.

On Linux, the browser opens as soon as the AutoRO web app responds; it no longer waits for Qwen to finish loading. If the desktop refuses the launch request, the terminal prints the exact URL and the browser error-log path.

On the first dashboard load of a browser session, AutoRO shows a three-second launch splash. Click anywhere on it or select Continue to dismiss it early. It does not repeat while navigating within the same browser session.

AutoRO binds to `127.0.0.1` and is designed for use on the computer where it is launched. Do not expose the Beta through a LAN address or reverse proxy.

## Estimate modes

### Pre-estimate - out of shop

Use when the vehicle has not yet been inspected and the uploaded Mitchell estimate represents requested or budget-planning work. AutoRO preserves the imported financial data and adds planning-oriented explanations. AI enrichment may fall back to local wording.

### Estimate - in shop

Use after entering a customer concern and/or technician findings. The output includes what was found, what is recommended, why it matters, and the detailed labour/parts breakdown from the estimate. If AI analysis reaches its time limit, AutoRO completes the document using source-grounded fallback mappings.

### Custom build package

Use for coordinated vehicle projects such as suspension, overland, performance, or staged builds. Enter the customer's build goal and intended-use notes. AI is limited to concise spelling, grammar, and title cleanup; local rules provide the technical presentation and the parser controls all financial fields.

The default PDF identity is:

```text
AutoRO
Built in the Bay - Calgary, Alberta
Powered by Real Shop Experience
Local Processing - Advisor Reviewed
autoroestimate@gmail.com
```

The pilot identity intentionally omits a shop street address, shop telephone number, and fax number. A customer phone imported from Mitchell may still appear in the customer-information block.

Generated files begin with `OUT_OF_SHOP_ESTIMATE`, `IN_SHOP_ESTIMATE`, or `CUSTOM_BUILD`, followed by the original estimate's readable filename identity. Internal upload IDs and generation timestamps are not included in customer-facing filenames.

## What to verify on every PDF

- Customer and vehicle match the source estimate.
- Every intended job is present once.
- Labour hours, parts, supplies, tax, and grand total match Mitchell.
- Part numbers and brand names were not altered.
- Customer-facing wording accurately reflects the advisor/technician notes.
- Custom-build titles and descriptions are professional and correctly spelled.
- Inspection language does not claim a condition that has not been confirmed.

Correct poor source descriptions in Mitchell when practical, then regenerate. AutoRO deliberately avoids aggressive rewriting that could silently change scope.

## Timing and fallback behavior

- Custom Build language cleanup: up to 15 seconds before local fallback.
- In-shop AI mapping: up to 45 seconds before local fallback.
- PDF parsing and rendering add a few seconds depending on estimate size and drive speed.
- CPU-only model execution is expected on systems where Llamafile reports that GPU layers are unavailable.

A completed PDF after an AI timeout is not automatically defective; it means fallback wording was used. It still requires advisor review.

## Reporting a Beta problem

Record:

- Time of the attempt.
- Selected estimate mode.
- Source PDF filename and number of jobs.
- Text of the visible error.
- Whether a PDF eventually completed.
- AutoRO version shown in the footer.

Relevant diagnostic files are under `runtime/logs/`:

- `autoro_*.log` for web/API and PDF workflow events.
- `qwen_*.log` for model loading, context-limit, and timeout events on Linux. On Windows, read the AutoRO Qwen Model window.

Do not edit or delete the active database while AutoRO is running. Runtime backups are stored under `runtime/Database/backups/`.
