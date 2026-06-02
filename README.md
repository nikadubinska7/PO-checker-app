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

Use the packaged app when available. Download the package for your laptop from the GitHub Actions build artifacts or a release:

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

The app will be created under `dist/PO Label Request App.app`.

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
5. Download the macOS or Windows artifact after the workflow finishes.

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

If a previous tracking row has the same PO with `Automation Status = requested`, the app writes a new `skipped` row with `Already requested in previous run`.

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
