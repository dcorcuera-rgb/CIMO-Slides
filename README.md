# Program Health Dashboard

This project builds and hosts a static dashboard from month-end issue data plus hierarchy data:

- `data/raw_issues.csv`: issue/action plan records
- `data/hierarchy.csv`: employee/manager hierarchy
- `data/legacy_action_plans.csv` (optional): legacy AP detail rows
- `data/new_action_plans.csv` (optional): new AP detail rows
- `data/program_config.json` (optional but recommended): population rules and monthly narrative updates

The pipeline script joins both datasets and outputs:

- `public/data/dashboard-data.json`

The static site reads that JSON and provides:

- Program-scoped KPI cards
- Health-story summary text
- Monthly update cards sourced from config
- Status and source breakdowns
- Self-serve filters for scope, status, severity, business unit, risk domain, and source
- Shareable URL filters
- CSV export of current filtered view
- Slide PNG export from the current dashboard state
- Slide notes copy for deck speaker notes or body text
- Local ad hoc dataset load (`.json`)
- Weekly CSV upload (`raw_issues.csv` + `hierarchy.csv`) directly in the browser

## Program scope and updates

Use `data/program_config.json` to define the program population and add reporting notes.

Example structure:

```json
{
  "program_name": "Program health dashboard",
  "scope_note": "What this dashboard is intended to represent.",
  "population_rules": {
    "include_any": [
      { "field": "business_unit", "contains": ["Bitcoin"], "label": "Business unit" },
      { "field": "risk_domain", "contains": ["Anti-Money Laundering"], "label": "Risk domain" }
    ],
    "exclude_any": [
      { "field": "issue_title", "contains": ["test"], "label": "Issue title" }
    ]
  },
  "kri_config": {
    "self_identified_keywords": ["Self-Identified"]
  },
  "cimo_intake_config": {
    "compliance_hierarchy_roots": ["Tyler Hand"],
    "compliance_level_1_risk_domain_keywords": ["Compliance |"]
  },
  "updates": [
    {
      "month": "2026-03",
      "title": "March close",
      "summary": "Open issues were stable month over month.",
      "bullets": ["Two overdue items were remediated.", "One new high-severity issue opened."]
    }
  ]
}
```

If `include_any` is empty, all records are treated as in scope unless they match an exclude rule.

CIMO intake classification is separate from program scope. A record is flagged as `in_cimo_intake` when any configured CIMO rule matches:

- issue owner is in the configured compliance hierarchy root
- issue approver is in the configured compliance hierarchy root
- risk domain matches the configured compliance level 1 keywords

## Local run

1. Build the dataset:

```bash
python3 scripts/build_dashboard_data.py
```

2. Serve the `public` folder:

```bash
python3 -m http.server 8080 --directory public
```

3. Open:

- `http://localhost:8080`

## Slide export

After filtering the dashboard to the view you want:

1. Click `Export slide (PNG)` to download a 16:9 summary slide image.
2. Drop the PNG into Google Slides or PowerPoint.
3. Click `Copy slide notes` if you want a text version of the same summary for speaker notes or slide body copy.

## Weekly update flow

### Option A: No-script dashboard upload

1. Serve the `public` folder:

```bash
python3 -m http.server 8080 --directory public
```

2. Open `http://localhost:8080`.
3. In **Filters**:
   - choose weekly `raw_issues.csv`
   - choose weekly `hierarchy.csv`
   - click **Load weekly CSVs**
4. Review scoped KPIs, health summary, updates, and issue details in the dashboard.

### Option B: Build static JSON (existing pipeline)

1. Replace `data/raw_issues.csv` with new weekly data.
2. Replace `data/hierarchy.csv` with latest hierarchy extract.
3. (Optional, recommended) Replace `data/legacy_action_plans.csv` and `data/new_action_plans.csv`.
4. Run `python3 scripts/build_dashboard_data.py`.
5. Commit and push to `main`.
6. GitHub Action publishes to Pages.

### Option C: Direct pull from Google Sheets links

1. Export environment variables:

```bash
export OPS_SHEET_ID="153cF0ATbZzdEqnhuFEXBz2ucKiod3cxf3u7dGchiFIE"
export HR_SHEET_ID="1swu4OVHjPJsF_nwtJEw-mVzZjwghs6sTgaT1yU3A17w"
export OPS_CONSOLIDATED_ISSUES_GID="<gid>"
export OPS_LEGACY_AP_GID="<gid>"
export OPS_NEW_AP_GID="<gid>"
export HR_HIERARCHY_GID="1984818498"
```

2. Pull the latest tab data to `data/*.csv`:

```bash
python3 scripts/fetch_google_sheets_csvs.py
```

3. Build dashboard data:

```bash
python3 scripts/build_dashboard_data.py
```

Note: the tabs must be accessible via direct CSV export URL (for example, shared for view access).

## Required CSV columns

### `raw_issues.csv`

- `issue_id`
- `issue_title`
- `status`
- `severity`
- `due_date`
- `issue_owner_email`
- `action_owner_email`

### `hierarchy.csv`

- `employee_email`
- `employee_name`
- `manager_email`
- `manager_name`
- `org_level`
- `department`

### `legacy_action_plans.csv` and `new_action_plans.csv` (optional)

At least one AP ID column must exist in each AP file:

- `action_plan_id` (or `ap_id`, `id`, `action_plan_number`)

Optional AP columns used for enrichment:

- `action_plan_title` (or `title`, `name`)
- `status`
- `due_date` (or `target_date`)

### Consolidated issues to AP linking

`raw_issues.csv` can include a column with linked AP IDs:

- preferred: `action_plan_ids`
- aliases: `ap_ids`, `action_plan_id`
- values can be comma/semicolon/pipe/newline-delimited

If AP CSVs are present and the issue-to-AP link column is available, the script enriches issues with linked AP detail. If the link column is missing, the build still succeeds and falls back to issue-level action-plan counts such as `Number of Action Plans` and `Number of Unresolved Action Plans`.

You can override column detection with env vars:

- `ISSUE_AP_IDS_COLUMN` (supports header name or Excel-style label like `BR`)
- `AP_ID_COLUMN` (default `action_plan_id`)

## Validation behavior

`scripts/build_dashboard_data.py` now validates required headers before building output:

- `raw_issues.csv`: `issue_id`, `issue_title`, `status`, `severity`, `due_date`, `issue_owner_email`, `action_owner_email`
- `hierarchy.csv`: `employee_email`, `employee_name`, `manager_email`, `manager_name`, `org_level`, `department`

## Hosting notes

- GitHub Pages deployment is configured in `.github/workflows/deploy-dashboard.yml`.
- Scheduled build runs every Monday at 12:00 UTC.
- In repository settings, enable GitHub Pages with **GitHub Actions** as the source.
