# AGENTS.md — Vendor Portal Label Request Automation App

## Project Objective
Build a cross-platform local automation app for requesting labels in the Deichmann vendor portal.

The app should allow the user to select an Excel file containing PO numbers and printer codes, then run a visible Playwright browser session that automates the portal workflow for each PO. The app must write processing results to a persistent tracking Excel file.

Portal URL:
https://vendor.deichmann.com/vendor.portal.web/

## Target Users
Business users who currently request labels manually in the supplier/vendor portal for 50–300 POs per batch.

## Platform Requirements
- Development may happen on macOS.
- Final app must work on both macOS and Windows.
- Prefer a local app, not cloud-hosted.
- Use Python + Playwright.
- Browser must run visibly for monitoring.
- Automation must not hijack the user’s mouse or keyboard, so the user can continue working in other applications while the bot runs.

## Recommended Architecture
Use a simple local application with:
- Python backend / automation engine.
- Playwright for browser automation.
- Excel input/output using openpyxl or pandas + openpyxl.
- Simple local UI using one of:
  - Streamlit,
  - PySide6/Tkinter,
  - FastAPI + minimal local HTML frontend.

Keep implementation simple and maintainable. Prioritize reliability over visual polish.

## Input File Requirements
The user selects an Excel file with at least these columns:

| Column | Example |
|---|---|
| PO | 5946692 |
| Printer | HK |

Input validation:
- Required columns: `PO`, `Printer`.
- Ignore empty PO rows.
- Trim spaces from PO and Printer values.
- Treat PO as text to preserve formatting.
- Detect duplicate POs and process only once per run, unless rows differ and there is a clear business reason to process duplicates.

## Output / Tracking File Requirements
The app should create or update a persistent tracking Excel file.

First run:
- Create a new output tracking file.

Following runs:
- Add information to the existing tracking file.
- Treat it as living tracking history.

Recommended output columns:
- `PO`
- `Printer`
- `Automation Status`
- `Error Explanation`
- `Processed Date`
- `Processed Timestamp`
- `Screenshot Path`
- `Run ID`

Definitions:
- `Processed Date`: date when the PO was processed, format `YYYY-MM-DD`.
- `Processed Timestamp`: exact local date/time when the PO was processed, format `YYYY-MM-DD HH:MM:SS`.

Statuses:
- `requested` — successfully requested.
- `error` — not successfully requested.
- `skipped` — not processed because it was already requested in tracking or intentionally skipped.
- `dry_run_success` — dry-run reached the final Request step but did not click Request.

Re-run logic:
- If the persistent tracking file already contains the same PO with `Automation Status = requested`, skip that PO automatically.
- Still write a new row or update current run output specifying that it was skipped because it was already requested.
- The row should contain the actual previous status in the explanation, for example: `Already requested in previous run`.

## Printer Matching Logic
The Excel file contains a printer code.

Mapping:
- `IN` -> select `India [50]`
- `VN` -> select `Vietnam [30]`
- `HK` -> select `Hong Kong [20]`
- Any other printer value except `IN` and `VN` -> select `Hong Kong [20]`

Printer matching should be robust:
- Trim spaces.
- Case-insensitive.
- If the dropdown label contains the expected target text, select it.
- Example: target `Hong Kong [20]`; match exact visible option when possible.

## Login Flow
Do not automate login.

Flow:
1. App opens the vendor portal in a visible browser.
2. User logs in manually.
3. User navigates to the relevant page if needed.
4. User clicks `Start Processing` in the app.
5. Bot begins processing POs.

Do not store portal credentials.

## Portal Workflow Per PO
For each PO:

1. Paste PO number into the `P.O.` field.
2. Click `Refresh`.
3. Wait until the page refresh completes and order result area is stable.
4. Detect whether the PO was found.
   - Expected found indicator: page/result text similar to `Page 1 of 1 / 1 Order/s found`, or visible result table row for the PO.
   - If no order info appears, mark `Automation Status = error`, `Error Explanation = PO not found`, save screenshot, continue to next PO.
5. Tick the checkbox under `Labels`.
6. Click `Request labels`.
7. On the request labels screen, check the `Status` column.
8. If `Status` is not `available`:
   - Mark `Automation Status = error`.
   - Set `Error Explanation` to the actual status text from the portal.
   - Save screenshot.
   - Continue to next PO.
9. If `Status` is `available`:
   - Select the correct factory/printer dropdown option using the printer mapping.
   - Use `Pick up` if it is already selected or required by the portal state. Do not change shipping mode unless needed.
   - Click `Request`.
10. Success detection:
   - Wait for popup/dialog containing `Labels requested successfully.`
   - Click `OK`.
   - Mark `Automation Status = requested`.
11. Continue with next PO.

## Multiple Labels Per PO
The portal only has one labels checkbox. There is no need to choose label type.

Even if the following label types are displayed after requesting labels, do not select among them:
- PRICE
- CARTON
- MASTER-CARTON

The bot should use the single available checkbox / request flow.

## Dry-Run Mode
Implement dry-run mode.

Dry-run behavior:
- Execute all steps up to the point immediately before the final `Request` click.
- Do not click the final `Request` button.
- Mark status as `dry_run_success` if the PO reaches that point successfully.
- Save screenshot showing the final state before Request.

Purpose:
- Allows safe testing in production portal without actually requesting labels.

## Human-Like Timing
The bot should not act instantly.

Implement moderate randomized delays:
- 0.5–2.0 seconds between normal interactions.
- 1.0–3.0 seconds after clicking Refresh or navigating/loading.
- Always wait for specific page elements/states where possible instead of relying only on fixed sleeps.

Do not intentionally make it very slow. Typical batch of 50–300 POs should be practical.

## Background Operation
The automation should run inside its own Playwright-controlled browser window.

Requirements:
- Do not use OS-level mouse movement automation.
- Do not use pyautogui for clicking/typing unless absolutely unavoidable.
- Use DOM-level Playwright interactions.
- User should be able to work in other windows while the automation runs.

## Error Handling
For each PO, catch errors and continue to the next PO unless the whole session is broken.

Error examples to handle:
- PO not found.
- Status is not available.
- Printer option missing.
- Request success popup not detected.
- Timeout after refresh.
- Portal session expired.
- Unexpected navigation/page structure change.

For errors:
- Write `Automation Status = error`.
- Write clear `Error Explanation`.
- Save screenshot.
- Continue with next PO when safe.

If session appears expired or login page appears:
- Pause processing.
- Ask user to log in again.
- Allow resume.

## UI Requirements
Minimum UI:
- Select input Excel file.
- Select or create tracking output Excel file.
- Button: Open Portal.
- Button: Start Processing.
- Button: Pause.
- Button: Resume.
- Button: Stop.
- Checkbox: Dry Run.
- Progress indicator: processed / total.
- Current PO being processed.
- Status table showing latest results.
- Link/path to output file and screenshot folder.

## Screenshots
Save screenshots for:
- Every error.
- Every dry-run success.
- Optional: every success if debug mode is enabled.

Recommended folder structure:

```text
runs/
  2026-06-02_143722_run001/
    screenshots/
    logs/
    tracking.xlsx
```

Screenshot filename example:

```text
PO_5946692_error_2026-06-02_143822.png
```

## Configurability
Selectors may need adjustment after inspecting the live portal HTML.

Create a config file for selectors and text constants, for example:

```yaml
portal_url: "https://vendor.deichmann.com/vendor.portal.web/"
texts:
  success_popup: "Labels requested successfully."
  available_status: "available"
printer_mapping:
  IN: "India [50]"
  VN: "Vietnam [30]"
  default: "Hong Kong [20]"
```

Selectors should be centralized, not hardcoded throughout the code.

## Development Notes
- Start with Playwright headed mode, not headless.
- Use robust selectors based on labels, visible text, roles, table headers, and nearby text when possible.
- Avoid brittle absolute XPath unless no better option exists.
- Add logging throughout.
- Add a mock/test mode if possible to test Excel handling without portal access.
- Include setup instructions for macOS and Windows.
- Include commands to install Playwright browsers.

## Deliverables
Create a working first version with:
- Source code.
- README with setup/run instructions for macOS and Windows.
- requirements.txt or pyproject.toml.
- Example input Excel file.
- Config file for portal selectors/mappings.
- Local UI.
- Playwright automation engine.
- Excel tracking output.
- Failure screenshots.
- Dry-run mode.

