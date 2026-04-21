#!/usr/bin/env python3
"""Download dashboard source CSVs directly from Google Sheets tabs."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def export_url(sheet_id: str, gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def download_csv(url: str, destination: Path) -> None:
    req = Request(url, headers={"User-Agent": "codex-dashboard-fetch/1.0"})
    try:
        with urlopen(req, timeout=30) as response:
            body = response.read()
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} downloading {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error downloading {url}: {exc.reason}") from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(body)


def main() -> int:
    try:
        ops_sheet_id = require_env("OPS_SHEET_ID")
        hr_sheet_id = require_env("HR_SHEET_ID")
        consolidated_gid = require_env("OPS_CONSOLIDATED_ISSUES_GID")
        legacy_ap_gid = require_env("OPS_LEGACY_AP_GID")
        new_ap_gid = require_env("OPS_NEW_AP_GID")
        hr_gid = require_env("HR_HIERARCHY_GID")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    sources = [
        (export_url(ops_sheet_id, consolidated_gid), DATA_DIR / "raw_issues.csv"),
        (export_url(ops_sheet_id, legacy_ap_gid), DATA_DIR / "legacy_action_plans.csv"),
        (export_url(ops_sheet_id, new_ap_gid), DATA_DIR / "new_action_plans.csv"),
        (export_url(hr_sheet_id, hr_gid), DATA_DIR / "hierarchy.csv"),
    ]

    for url, target in sources:
        print(f"Downloading {target.name} ...")
        download_csv(url, target)
        print(f"Wrote {target}")

    print("Done. Run: python3 scripts/build_dashboard_data.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
