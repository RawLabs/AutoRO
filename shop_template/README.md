# AutoRO 1.3.0-beta.1 Multi-Shop Deployment Template

This directory contains the framework and templates required to deploy clean, configured instances of AutoRO to new drives or environments.

The Beta uses one shared Qwen3 llamafile endpoint for translation and estimate wording. Generated shop configuration points both model URLs at the selected model port.

---

## 📂 Framework Directory Layout

```text
shop_template/
├── README.md                       # This deployment guide
├── deploy_shop.py                  # Command-line configuration & deployment wizard
├── .env.template                   # Configuration template with detailed comments
└── AutoRO_shop_demo/               # The template instance ("AutoRO Shop Demo")
    ├── .env                        # Default configuration for the demo shop
    └── runtime/
        ├── Database/
        │   └── autoro.db           # Empty SQLite database pre-initialized with all database tables
        ├── data/                   # Copied reference data maps, canned jobs, and BG rules
        ├── reports/                # Empty folder for monthly reports
        └── logs/                   # Empty folder for server and model diagnostic logs
```

---

## 🚀 Deployment Guide

### Option A: Automatic Deployment using `deploy_shop.py` (Recommended)

Run the Python deployment wizard from the terminal/command line. This works on both Linux and Windows (using the portable Python environment on the USB drive).

#### On Linux:
```bash
python3 shop_template/deploy_shop.py
```

#### On Windows (using the portable python on the drive):
```cmd
Tools\Python\python-3.12.10-embed-amd64\python.exe shop_template\deploy_shop.py
```

#### What the wizard does:
1. **Prompts** you for target path, shop name, server port, operations PIN code, and model ports.
2. **Copies** the core system folders (`app`, `Llamafile`, `Models`, `Tools`, launcher scripts) to the target directory.
3. **Copies only allowlisted application paths.** Estimate uploads, generated PDFs, import records, logs, reports, `.env`, Git history, caches, and the source shop database are never copied.
4. **Validates** that the template database contains zero business records before using it, then creates empty runtime/output directories for the new shop.
5. **Generates** a custom, ready-to-run `.env` at the destination root.
6. **Updates** the launcher scripts (`.bat`, `.ps1`, `.sh`) on the new drive to bind to the requested custom port.

The deployment retains AutoRO's loopback-only security boundary. A different local port supports multiple instances on one computer; it does not expose AutoRO to the shop LAN.

The target directory must be empty. The wizard intentionally refuses to merge a new deployment with an existing or partial shop installation.

---

### Option B: Manual Deployment

If you want to assemble a new shop drive manually:

1. **Format/Prepare Target Drive**: Insert the new USB drive and ensure it has a compatible filesystem (e.g. NTFS or exFAT for Windows compatibility).
2. **Copy Core Files**: Copy the following folders and files from the root of the source drive to the root of the target drive:
   - `app/`
   - `estimate_conversion/images/`
   - `estimate_conversion/scripts/`
   - `estimate_conversion/workspace/estimates/`
   - `Llamafile/`
   - `Models/`
   - `Tools/`
   - `docs/`
   - `dev_tools/`
   - Launchers: `Double Click to Start AutoRO Windows Useres .bat`, `Launch AutoRO (PowerShell).ps1`, `start_autoro_linux.sh`
   - Configs & Setup: `Modelfile`, `requirements.txt`, `install_linux_dependencies.sh`, `RELEASE_MANIFEST.json`
3. **Copy Template Runtime**: Copy the `/shop_template/AutoRO_shop_demo/runtime/` folder to the target root. This provides the clean initialized database file (`Database/autoro.db`) and standard reference data (`data/`).
4. **Create Config**: Copy `/shop_template/.env.template` to the root of the target drive as `.env` and customize it (specifically set `AUTORO_MANAGEMENT_CODE` and LLM URLs).
5. **Create Empty Runtime Directories**: Create `runtime/logs`, `runtime/reports`, `estimate_conversion/workspace/uploads`, `estimate_conversion/workspace/autoro_outbox`, `estimate_conversion/workspace/import_records`, and `app/static/inshop_temp`. Do not copy these directories from an active shop.

Never copy the full `estimate_conversion/workspace/`, `runtime/`, or `.env` from an active shop. Those locations contain per-shop operational data.

---

## 🛠️ Customizing the Port on the New Drive

If you want to run multiple drives/instances of AutoRO on the same machine simultaneously, make sure to:
1. Assign distinct ports (e.g. `8000`, `8002`, `8003`) in their respective `.env` files using `deploy_shop.py` or editing the `.env` manually.
2. Ensure you modify the port settings inside the launcher scripts (`Double Click to Start AutoRO Windows Useres .bat`, `Launch AutoRO (PowerShell).ps1`, `start_autoro_linux.sh`) so they connect and open the browser on the correct port. The `deploy_shop.py` script does this automatically.
