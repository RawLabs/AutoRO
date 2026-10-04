# AutoRO Deficiency Assessment

> Historical assessment. Several findings were subsequently mitigated. This file is retained as assessment history, not current operating documentation; use the root README for current AutoRO Communication Layer behavior.

Date: 2026-07-11  
Reviewed target: current working-tree snapshot based on Git revision `30d489cf844d8bf1a770be9db9e9aa46523a9085`  
Assessment type: focused first-party application security, privacy, reliability, and maintainability review

## Executive Summary

AutoRO has a sound local-first product direction and several useful controls: loopback binding by default, parameterized SQL in reviewed query paths, fixed-argument subprocess calls, output-path confinement in the estimate preview flow, filename sanitization, structured logging, model-call timeouts, and escaped PDF paragraph content.

The current snapshot is not ready for use with sensitive production data on a shared or network-reachable workstation. The most important deficiencies are broad unauthenticated APIs, committed customer/operational artifacts, a DOM-XSS path, report-directory traversal, weak management authentication, and insufficient resource limits around uploads and PDF parsing.

Risk summary:

| Priority | Count | Meaning |
|---|---:|---|
| P0 | 2 | Address before distributing the repository or adding real customer data |
| P1 | 5 | Address before broader shop deployment or any non-loopback exposure |
| P2 | 6 | Important hardening, privacy, and operational reliability work |

## P0 — Immediate

### D-01: Customer and operational artifacts are committed to Git

**Risk:** High — confidentiality and trade-secret exposure  
**Confidence:** High

Git currently tracks 99 operational/configuration files under `.env`, `estimate_conversion/workspace`, `app/static/inshop_temp`, and `runtime`. Tracked filenames and manifests include customer names, vehicle descriptions, estimate identifiers, generated PDFs, import records, and management reports. Adding these paths to `.gitignore` does not remove already tracked content or erase them from Git history.

Impact includes disclosure through repository copies, backups, developer machines, release bundles, or future remote hosting. This is especially serious because the repository is explicitly described as containing trade secrets and customer/shop data.

Required remediation:

1. Stop adding production/customer artifacts to Git.
2. Inventory every tracked operational file and classify it as synthetic or real.
3. Move real data to a separately permissioned runtime volume.
4. Remove artifacts from the index and, where exposure warrants it, rewrite repository history and rotate affected credentials/codes.
5. Replace committed examples with clearly synthetic fixtures.
6. Add a release check that fails if `.env`, PDFs, uploads, import records, databases, or reports enter the release identity.

### D-02: Broad customer/shop APIs have no authentication or authorization

**Risk:** High when reachable; Medium under strictly enforced loopback-only deployment  
**Confidence:** High  
**CWE:** CWE-306, CWE-862, CWE-639

There is no authentication middleware in `app/main.py`. Routes in `app/routes.py` allow callers to list and retrieve cases, read and edit advisor-queue items, clear the queue, approve/correct/update arbitrary cases, upload/read/analyze/save estimates, and generate/stream PDFs. Database responses include customer complaints, technician notes, vehicle information, model prompts/responses, corrections, and approval state.

Integer identifiers make object enumeration straightforward. Parameterized SQL prevents SQL injection but does not provide object authorization.

Required remediation:

- Add one explicit authentication boundary for every `/api/*` route except a minimal health endpoint.
- Separate advisor, technician, and manager privileges.
- Enforce authorization per object and action, not only at page-navigation level.
- Default-deny new routes and add authorization tests for every mutation and sensitive read.
- Preserve loopback binding as defense in depth, not as the authentication mechanism.

## P1 — High Priority

### D-03: Uploaded/model-derived text reaches `innerHTML`

**Risk:** Medium, with high integrity impact after execution  
**Confidence:** High static trace  
**CWE:** CWE-79

`app/static/js/estimate_inshop.js:114` builds an estimate card with `innerHTML`. Unescaped values include the parsed PDF job title and model-derived fields at lines 116, 128, 131, 134, and 137. A payload such as a closing `textarea` tag followed by an event-bearing element can escape the intended context and execute script when an advisor opens the estimate.

The script runs in AutoRO's origin and can call the otherwise unauthenticated APIs, turning display injection into customer-record and estimate manipulation.

Required remediation:

- Replace the template with DOM node construction using `textContent` and textarea `.value`.
- If HTML is genuinely required, sanitize with a well-maintained allowlist sanitizer and test each render context.
- Add a Content Security Policy that blocks inline script as secondary containment.
- Add regression fixtures containing HTML, closing tags, quotes, and event attributes.

### D-04: Manager-selected report month can escape the reports directory

**Risk:** Medium; potentially High when the default manager code remains active  
**Confidence:** High static validation  
**CWE:** CWE-22, CWE-200

`app/operations_reports.py:39-42` joins the configured reports root with the request-controlled `month` without an allowlist or containment check. The resulting directory is globbed and XLSX files are parsed and returned at lines 124-171. Values such as `../docs` can select another directory; an absolute path can replace the base under Windows path semantics.

The gate is weakened by the shipped `2470` code. Disclosure is constrained to readable `.xlsx` files directly inside the chosen directory, but the repository already contains an XLSX outside the report root.

Required remediation:

- Accept only a strict `YYYY-MM` value and reject every other form.
- Resolve the candidate directory and prove it is a child of the resolved reports root.
- Return logical report identifiers, not absolute filesystem paths.
- Replace the shared code with proper manager authentication.

### D-05: Estimate run/preflight accepts arbitrary absolute PDF paths

**Risk:** Medium  
**Confidence:** High static trace  
**CWE:** CWE-22, CWE-200

`EstimateConversionRequest.input_pdf` reaches `_resolve_input_pdf` in `app/estimate_conversion.py`, which accepts absolute paths without proving they are under the upload directory. The unauthenticated run/preflight endpoints then parse the selected PDF and return structured customer, vehicle, and job information.

This is not arbitrary-byte file read: the target must be a usable PDF and the response is a structured subset. It is nevertheless a local-file disclosure and existence oracle for known or guessable PDFs.

Required remediation:

- Replace client-supplied filesystem paths with opaque upload IDs.
- Resolve the server-side stored path and enforce containment beneath the upload root.
- Revalidate extension, magic bytes, regular-file status, and symlink behavior immediately before parsing.

### D-06: Browser-to-loopback requests can trigger state changes

**Risk:** Medium  
**Confidence:** High for no-body/raw-body POST endpoints  
**CWE:** CWE-352

The application has no CSRF token, Origin validation, or Host allowlist. A malicious website opened in the shop browser can issue simple cross-origin POSTs to loopback endpoints that require no JSON preflight, including queue processing/clearing/retry operations, PDF generation, and raw-body upload endpoints. Same-origin responses may be unreadable because of browser CORS rules, but the state-changing request can still execute.

Required remediation:

- Require authenticated sessions plus CSRF tokens for browser mutations.
- Reject untrusted `Origin`/`Referer` values and enforce trusted Host headers.
- Require a non-simple custom header on API mutations as additional browser-side friction.
- Avoid using GET for any state change and test cross-origin request behavior.

### D-07: Upload and parser resource controls are incomplete

**Risk:** Medium availability risk  
**Confidence:** High  
**CWE:** CWE-400

Multiple routes call `await request.body()`, buffering the entire request before size checks. The in-shop upload has no demonstrated byte cap. PDF extraction captures all `pdftotext` output in memory; parser stages create additional line lists and JSON copies. Some parser subprocess calls have no timeout or output cap, and concurrent unauthenticated requests amplify the impact.

Required remediation:

- Enforce request limits before buffering and stream uploads to bounded temporary files.
- Limit pages, extracted bytes, parser runtime, concurrent conversions, and generated output size.
- Run document parsing in a constrained worker process with memory/CPU limits.
- Validate PDF structure with a hardened library/toolchain and reject encrypted, malformed, or excessively complex inputs.
- Add rate limits and a bounded work queue.

## P2 — Important Hardening

### D-08: Management authentication is a documented shared default

**Risk:** Medium  
**Confidence:** High

The default management code `2470` exists in configuration and documentation. Validation is a plain equality check with no rate limit, lockout, user identity, session expiry, or meaningful audit trail. `/api/management/report` is not protected by this code at all.

Replace it with per-user authentication, a slow password hash or platform identity integration, role checks, short-lived sessions, rate limiting, and audit logging. Refuse startup with a known default when sensitive reports are enabled.

### D-09: Failed and successful conversions leave sensitive temporary data

**Risk:** Medium on shared workstations; Low on a dedicated locked-down host  
**Confidence:** High

`decision_pipeline.parse_mitchell` creates a `NamedTemporaryFile(delete=False)` containing the parsed customer, phone, VIN, plate, mileage, and job manifest, then reads it without a `finally` cleanup. These files can persist in the OS temporary directory and accumulate.

Use a private application temp directory with restrictive permissions and delete files in `finally`. Prefer in-memory pipes only after enforcing strict output bounds.

### D-10: Unauthenticated diagnostics disclose environment details

**Risk:** Low to Medium  
**Confidence:** High

`/api/diag` returns matching process command lines, raw model-service responses, or exception text. `/api/health` returns model URLs, provider information, and the database path. These details improve attacker reconnaissance and may reveal usernames, paths, model flags, or service topology.

Keep public health output to a boolean/status identifier. Put diagnostics behind manager authentication and redact paths, arguments, upstream bodies, and exceptions.

### D-11: Model clients accept unbounded response bodies

**Risk:** Low to Medium  
**Confidence:** Medium

The Ollama and llamafile clients call `response.read()` without a byte limit. Timeouts and requested token limits do not guarantee a compromised or misconfigured server will honor response size. A large body can exhaust the FastAPI process.

Read through a strict byte-limited stream, reject excessive `Content-Length`, cap decompressed bytes, and isolate model calls from the web worker.

### D-12: Dependency and release reproducibility are weak

**Risk:** Operational/security hardening gap

`requirements.txt` uses open-ended minimum versions and has no lockfile or hashes. A rebuild can silently receive materially different FastAPI, Starlette, ReportLab, Pillow, or transitive packages. Bundled executables/models increase supply-chain importance but the current review found no concise provenance/SBOM contract.

Pin exact reviewed versions, generate hashes, maintain an SBOM, record upstream source/signature/license, and verify bundled executable/model hashes before startup and release.

### D-13: Automated test execution is not standardized

**Risk:** Quality and regression gap

The attempted standard command `python -m unittest dev_tools.test_sanity_checks dev_tools.test_inshop_flow` failed because `dev_tools` is not an importable package. Tests are primarily standalone scripts and do not appear wired into a single repeatable security/regression command.

Adopt pytest or a documented unittest discovery layout, add an importable test package, and make one offline command cover authorization, path containment, XSS fixtures, upload limits, cleanup, estimate parsing, and release identity.

## Positive Controls Confirmed

- Primary launchers bind FastAPI and model services to `127.0.0.1` by default.
- Reviewed database query values are parameterized; dynamic migration identifiers are developer-owned constants.
- Reviewed subprocess calls use argument arrays rather than `shell=True`.
- Estimate output preview uses resolved-path containment checks.
- Generated in-shop PDF filenames are allowlist-sanitized.
- Reviewed PDF paragraph content is escaped before ReportLab markup interpretation.
- Several frontend renderers correctly use `textContent` or `.value`; these are useful patterns for repairing the XSS sink.
- Model calls have timeouts, and one upload flow checks `%PDF` plus a 25 MiB saved-content limit.

## Recommended Remediation Order

1. Quarantine and purge committed operational/customer data; rotate the management code.
2. Add authentication, authorization, and CSRF/Origin/Host controls.
3. Remove the `innerHTML` sink and close report/upload path traversal.
4. Introduce streaming upload limits and isolated bounded PDF parsing.
5. Clean sensitive temp files and minimize diagnostics.
6. Pin dependencies, add provenance/SBOM verification, and standardize tests.

## Scope and Limitations

The review covered the principal FastAPI routes, database layer, schemas/configuration, model clients, report ingestion, critical browser renderers, estimate/PDF parsing and generation pipeline, and repository data boundaries. Generated PDFs, runtime databases, model binaries, bundled Python/Poppler internals, recycled files, and repeated shop-template/runtime copies were inventoried but were not treated as first-party application source.

The repository was already dirty when review began. No application source, customer data, configuration, or Git history was modified. Findings are based primarily on full-file static review and bounded local checks; destructive parser payloads and live exploitation against operational data were intentionally not performed.
