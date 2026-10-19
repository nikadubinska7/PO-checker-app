# Vendor Portal Label Request Automation

Local desktop app for requesting labels in the Deichmann vendor portal from an Excel list of PO numbers and printer codes.

The app uses a visible Playwright browser. Login is manual: click **Open Portal**, log in yourself, navigate to the relevant portal page if needed, then click **Start Processing**.

## What It Does

- Reads an Excel input file with `PO` and `Printer` columns.
- Keeps a persistent tracking Excel file across runs.
- Skips POs already marked `requested` in the tracking file.
- Uses headed Playwright browser automation, without OS-level mouse or keyboard automation.
- Supports dry-run mode that stops before the final `Request` click.
- Saves screenshots for errors and dry-run successes.
- Writes run folders under `runs/YYYY-MM-DD_HHMMSS_runNNN/`.

## For Business Users

Use the packaged app when available. Download the package for your laptop from the GitHub Releases page:

`https://github.com/nikadubinska7/PO-checker-app/releases/tag/latest-desktop-build`

- macOS: open `PO Label Request App.app`.
- Windows: open `PO Label Request App.exe`.

The packaged app includes the Python application dependencies and Playwright browser files. Business users do not need to install Python, Git, Playwright, or run terminal commands.

First launch notes:

- macOS unsigned internal builds may require right-clicking the app and choosing **Open** the first time.
- Windows unsigned internal builds may show Microsoft Defender SmartScreen. Choose **More info** and **Run anyway** if you trust the internal build.

Run outputs are saved in a user-writable app folder:

- macOS: `~/Library/Application Support/PO Label Request App`
- Windows: `%LOCALAPPDATA%\PO Label Request App`

## Developer Setup: macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
python -m playwright install chromium
python scripts/create_example_input.py
python -m po_label_app
```

## Developer Setup: Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
python -m playwright install chromium
python scripts\create_example_input.py
python -m po_label_app
```

## Running The App

1. Activate the virtual environment.
2. Run:

```bash
python -m po_label_app
```

3. Select an input Excel file.
4. Select or create the persistent tracking Excel file.
5. Keep **Dry Run** enabled for the first production test.
6. Click **Open Portal**.
7. Log in manually in the browser.
8. Navigate to the correct portal page if the portal does not open there directly.
9. Click **Start Processing**.

## Downloading The Install Package

Open:

`https://github.com/nikadubinska7/PO-checker-app/releases/tag/latest-desktop-build`

Then download:

- Windows: `PO-Label-Request-App-Windows.zip`
- macOS: `PO-Label-Request-App-macOS.zip`

For Windows, extract the ZIP and double-click `PO Label Request App.exe`.

For macOS, extract the ZIP and open `PO Label Request App.app`.

If macOS blocks the app because it was downloaded from the internet, remove quarantine on the extracted folder:

```bash
xattr -cr ~/Downloads/PO\ Label\ Request\ App\ macOS
```

Then right-click `PO Label Request App.app` and choose **Open**.

## Building Double-Click Desktop Packages

Build packages on the same operating system you want to distribute to. Build the macOS app on a Mac. Build the Windows app on Windows.

### Build macOS `.app`

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-build.txt
pip install -e .
python -m playwright install chromium
python scripts/create_example_input.py
python scripts/build_desktop.py
```

The app package folder will be created under `dist/PO Label Request App macOS`.

### Build Windows `.exe`

In PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-build.txt
pip install -e .
python -m playwright install chromium
python scripts\create_example_input.py
python scripts\build_desktop.py
```

The app will be created under `dist\PO Label Request App\PO Label Request App.exe`.

To distribute it, zip the whole `dist\PO Label Request App` folder. The `.exe` needs the files beside it, including bundled Playwright browser files.

### Build Packages In GitHub

The repository includes `.github/workflows/build-desktop.yml`.

To build both packages without using terminal on the target laptops:

1. Open the repository on GitHub.
2. Go to **Actions**.
3. Select **Build desktop packages**.
4. Click **Run workflow**.
5. After the workflow finishes, go to **Releases**.
6. Open **Latest Desktop Build**.
7. Download the macOS or Windows ZIP package.

### Installer Notes

The build above creates a double-clickable app bundle/folder. A polished installer can be added later:

- macOS: package the `.app` into a `.dmg`.
- Windows: wrap the `dist\PO Label Request App` folder with Inno Setup or WiX.

## Input Excel Format

Required columns:

| PO | Printer |
| --- | --- |
| 5946692 | HK |
| 5946693 | IN |
| 5946694 | VN |

Rules:

- Empty PO rows are ignored.
- PO and Printer values are trimmed.
- PO values are handled as text.
- Duplicate POs in the same input are processed once; duplicate rows are written as `skipped`.

An example workbook is generated at `examples/example_input.xlsx`.

## Tracking Output

The tracking workbook contains:

- `PO`
- `Printer`
- `Automation Status`
- `Label Request Mode`
- `Error Explanation`
- `Processed Date`
- `Processed Timestamp`
- `Screenshot Path`
- `Run ID`

Statuses:

- `requested`
- `error`
- `skipped`
- `dry_run_success`

In All available labels mode, a previous `requested` tracking row skips that PO with explanation `released before`. In All except CARTON / MASTER-CARTON mode, the app checks the current portal rows even when a PO was requested previously, because the earlier request may cover only PRICE. It requests remaining available labels and records `skipped` / `released before` only when all eligible rows are already requested, released, or printed.

`Label Request Mode` records how the PO was processed:

- `all_available` requests all labels selected by the portal workflow.
- `exclude_cartons` selects every available label type except `CARTON` and `MASTER-CARTON`. Historical `price_only` rows remain unchanged.

## Printer Mapping

Configured in `config.yaml`:

- `IN` selects `India [50]`
- `VN` selects `Vietnam [30]`
- `HK` selects `Hong Kong [20]`
- Any other value selects `Hong Kong [20]`

Matching is case-insensitive and trims spaces.

## Configuring Portal Selectors

Selectors and text constants are centralized in `config.yaml`.

The portal HTML may require adjustment after live inspection. Prefer adding stable labels, button roles, visible text, or narrow CSS selectors in `config.yaml`. Avoid absolute XPath unless there is no better option.

## Dry-Run Mode

Dry-run mode executes each PO up to the final Request button and does not click it. Successful dry-runs are written as `dry_run_success` and include a screenshot of the final state.

## Label Mode

Use the `Label Mode` dropdown in the app before starting a run:

- `All available labels` keeps the existing behavior.
- `All except CARTON / MASTER-CARTON` requests every row with `Status = available` except `CARTON` and `MASTER-CARTON`, including other label types such as PRICE and INFO.

The exclusion mode unchecks excluded and unavailable rows before requesting. If all eligible rows were already released, it records `skipped` with `released before`. Genuine unavailable or unreadable statuses remain errors with screenshots and the actual cause. Available PRICE, INFO, and SOURCE-TAGGED rows are selected together; CARTON and MASTER-CARTON are unchecked.

## Mock Excel Check

Use this to verify input/tracking logic without opening the portal:

```bash
python -m po_label_app --mock-excel --input examples/example_input.xlsx --tracking runs/mock_tracking.xlsx
```

## Local Tests

```bash
python -m unittest discover -s tests
```

## Notes

- Do not store portal credentials in this app.
- Browser automation runs through Playwright DOM APIs, not `pyautogui`.
- If the portal session expires, the app pauses and asks you to log in again before resuming.

## Speed and rollback

`timing.speed_multiplier` defaults to `3.0`: randomized interaction and loading delays take one-third of their previous time. Set it to `1.0` for the original delays. Portal readiness and success timeouts remain unchanged; actual batch speed depends on portal response times.

The pre-revision source and existing desktop builds are preserved in `backups/pre_revision_2026-10-19/`. To restore, close the app and extract `source.tar.gz` into a separate folder, then follow the setup instructions there. The archive includes the original configuration and local source changes. The original packaged apps can be opened directly from that backup's `dist` folder. Keep using the same tracking workbook to preserve request history. This backup is local and is not included in Git or distributed builds.
