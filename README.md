# CACM External Cost Ingest (`external-data-ingestion-sync`)

Automates **FOCUS CSV** validation and **Harness External Data Provider** upload for Cloud & AI Cost Management.

**GitHub:** [Samriddha11/external-data-ingestion-sync](https://github.com/Samriddha11/external-data-ingestion-sync)

## Connected Harness scope (implementation target)

| Field | Value |
|--------|--------|
| Account ID | `SxuV0ChbRqWGSYClFlMQMQ` |
| Org | `sam` |
| Project | `CCMDemo` |
| API secret (project) | `Sam-API-Key` |

Pipeline: **`cacm_external_cost_ingest`** (created via Harness MCP).

## Features

- **Provider adapters**: `custom` (pass-through), `snowflake`, `databricks` → FOCUS transform
- **Hard validation**: required FOCUS columns, `ChargeCategory`, ISO dates, 20 MB limit
- **Ingest**: signed URL → `filesinfo` → `dataingestion` APIs
- **Multi-cloud object storage**: download CSVs from **AWS S3**, **GCP GCS**, or **Azure Blob** (`object_uri` / pipeline `object_uri`)

## Local run

```bash
cd "/path/to/external-data-sync-job"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export HARNESS_API_KEY="your-key"
python -m cacm_external_ingest.cli \
  --account-id SxuV0ChbRqWGSYClFlMQMQ \
  --api-key "$HARNESS_API_KEY" \
  --provider-id "<external-data-provider-uuid>" \
  --provider-type custom \
  --invoice-period 20260101-20260131 \
  --input-file examples/sample_focus.csv \
  --validate-only
```

Remove `--validate-only` to upload after validation.

## Pipeline inputs

| Input | Description |
|--------|-------------|
| `provider_id` | External Cost Data Source UUID (CACM → Account Settings → External Cost Data Sources) |
| `provider_type` | `custom`, `snowflake`, or `databricks` |
| `invoice_period` | `YYYYMMDD-YYYYMMDD` |
| `object_uri` | Any cloud CSV (overrides the `object_uri_*` fields below) |
| `object_uri_s3` | AWS — `s3://bucket/path/file.csv` |
| `object_uri_gcs` | GCP — `gs://bucket/path/file.csv` |
| `object_uri_azure` | Azure — blob HTTPS URL or `azure://account/container/file.csv` |
| `use_sample` | `true` to use bundled `examples/sample_focus.csv` (smoke test) |
| `validate_only` | `true` to skip ingest API calls |
| `repo_object_prefix` | Any cloud folder with this repo (overrides `repo_object_prefix_*`) |
| `repo_object_prefix_s3` | AWS — `s3://bucket/external-data-sync-job/` |
| `repo_object_prefix_gcs` | GCP — `gs://bucket/external-data-sync-job/` |
| `repo_object_prefix_azure` | Azure — `https://acct.blob.core.windows.net/container/external-data-sync-job/` |
| `repo_path` | Optional — absolute path to this repo on the delegate host |

## Cloud object URIs

The runner needs the matching CLI and credentials.

| Cloud | Example `object_uri` | CLI | Auth |
|--------|----------------------|-----|------|
| AWS | `s3://my-bucket/path/file.csv` | `aws` | IAM / `aws configure` / instance role |
| GCP | `gs://my-bucket/path/file.csv` | `gcloud storage` or `gsutil` | `gcloud auth` / workload identity |
| Azure | `https://acct.blob.core.windows.net/container/path/file.csv` or `azure://acct/container/path/file.csv` | `az` | `az login`, connection string, or managed identity |

CLI flags: `--object-uri` (preferred), `--object-prefix` for batch CSVs with `--invoice-periods-json`.  
`--s3-uri` / `--s3-prefix` remain aliases for S3.

```bash
# GCS
python -m cacm_external_ingest.cli ... \
  --object-uri gs://my-bucket/cost/august.csv \
  --provider-type snowflake --derive-invoice-period-from-csv

# Azure
python -m cacm_external_ingest.cli ... \
  --object-uri "https://mystorage.blob.core.windows.net/exports/TA-Identity-August2026-Snowflake.csv" \
  --provider-type snowflake --derive-invoice-period-from-csv
```

## S3 testing (July / August)

You already ingested **June** via the UI. To test **July and August** from S3 without re-uploading June:

### 1. Layout in S3

Use one folder and one CSV per month (FOCUS or raw + `custom` adapter), each **≤ 20 MB**:

```text
s3://<your-bucket>/cacm-external-test/
  july-forecast.csv
  august-forecast.csv
```

### 2. Invoice periods (must match CACM month rows)

| Month | `invoice_period` |
|--------|-------------------|
| July 2026 | `20260701-20260731` |
| August 2026 | `20260801-20260831` |

Provider ID (from URL `selectedProvider=`): `6aaa161da729b114c9ffc862`

### 3. AWS access

The **Harness pipeline** (`local` delegate) or your laptop needs:

- **AWS CLI** installed (`aws s3 cp` / `aws s3 ls`)
- Credentials via env, `~/.aws/credentials`, or an **AWS connector** on the runner

`CCMDemo` does not yet have an AWS connector; for pipeline runs, either add one or run the CLI on a machine with S3 access.

### 4. Where the job code lives (pick one)

**Recommended — GitHub (works on K8s delegates)**  
The Custom stage runs on your **K8s delegate**. It clones the public repo with `git clone` (no Mac path, no S3 code bucket):

| Pipeline input | Example |
|----------------|---------|
| `git_repo_url` | `https://github.com/Samriddha11/external-data-ingestion-sync.git` (default) |
| `git_branch` | `main` |

Delegate image/pod must have **`git`**, **`python3`**, and (for CSV download) **`aws`** / `gcloud` / `az`.

**Alternative — S3 / GCS / Azure prefix**  
If you are not using Git yet, upload the project to object storage (one-time):

```bash
cd "/path/to/external-data-sync-job"

# AWS
aws s3 sync . s3://YOUR-BUCKET/external-data-sync-job/ --exclude ".venv/*" --exclude ".git/*"

# GCP
gcloud storage cp -r . gs://YOUR-BUCKET/external-data-sync-job/ --exclude=".venv/**"

# Azure (container must exist; blobs under prefix external-data-sync-job/)
az storage blob upload-batch --destination YOUR_CONTAINER --source . \
  --account-name YOUR_ACCOUNT --pattern "external-data-sync-job/*"
```

Pipeline: set **`repo_object_prefix_s3`**, **`repo_object_prefix_gcs`**, or **`repo_object_prefix_azure`** (or generic **`repo_object_prefix`**).

### 5. Pipeline run (one month per execution)

In [CACM External Cost Ingest](https://app.harness.io/ng/account/SxuV0ChbRqWGSYClFlMQMQ/all/orgs/sam/projects/CCMDemo/pipelines/cacm_external_cost_ingest/pipeline-studio):

| Input | July run | August run |
|--------|----------|------------|
| `provider_id` | `6aaa161da729b114c9ffc862` | same |
| `invoice_period` | `20260701-20260731` | `20260801-20260831` |
| `repo_object_prefix` | `s3://YOUR-BUCKET/external-data-sync-job` | same |
| `object_uri` | `s3://<bucket>/.../july.csv` (or `gs://` / Azure URL) | August file URI |
| `use_sample` | `false` | `false` |
| `validate_only` | `true` first, then `false` | same |

**Smoke test:** `use_sample=true`, `validate_only=true`, `repo_object_prefix` as above, `invoice_period=20260101-20260131`, `derive_invoice_period_from_csv=false`.

Run twice (July, then August). Do **not** set `use_sample=true` when using real `object_uri`.

### 6. Local / batch CLI (both months in one command)

```bash
export HARNESS_API_KEY="..."
export BUCKET=your-bucket
# Edit URIs in scripts/s3-july-august.example.sh then:
VALIDATE_ONLY=true bash scripts/s3-july-august.example.sh
```

Or single file:

```bash
python -m cacm_external_ingest.cli \
  --account-id SxuV0ChbRqWGSYClFlMQMQ \
  --api-key "$HARNESS_API_KEY" \
  --provider-id 6aaa161da729b114c9ffc862 \
  --provider-type custom \
  --invoice-period 20260701-20260731 \
  --s3-uri s3://your-bucket/cacm-external-test/july-forecast.csv \
  --validate-only
```

### 7. Monthly schedule (5th of each month)

**Cron (UNIX, UTC):** `0 6 5 * *` → 06:00 UTC on day 5 (~11:30 AM IST).

**Option A — UI**

1. Open [CACM External Cost Ingest](https://app.harness.io/ng/account/SxuV0ChbRqWGSYClFlMQMQ/all/orgs/sam/projects/CCMDemo/pipelines/cacm_external_cost_ingest/pipeline-studio) → **Triggers** → **New Trigger** → **Cron**.
2. Schedule: **Custom** → **UNIX** → `0 6 5 * *` (adjust hour for your timezone; Harness default is UTC).
3. **Pipeline Input:** set `provider_id`, `repo_object_prefix_*`, and `object_uri_*` (see `harness/trigger-monthly-day5.yaml`).
4. **Create Trigger** → use **Run** once on the trigger to test before waiting for the 5th.

**Option B — YAML in repo**

- Trigger template: `harness/trigger-monthly-day5.yaml`
- Optional input set: `harness/input-set-monthly-ingest.yaml`

**Monthly CSV naming:** Cron inputs are static. Use a stable object key each month (e.g. `s3://bucket/incoming/monthly-snowflake.csv` overwritten by your export job) or update the trigger input / input set when the path changes. Harness does not support dynamic expressions in trigger pipeline variables for cron.

For GCP/Azure scheduled runs, set `repo_object_prefix_gcs` / `repo_object_prefix_azure` and `object_uri_gcs` / `object_uri_azure` in the trigger input instead of the S3 fields.

### 8. Verify in Harness

After ingest (`validate_only=false`), check **External Cost Data Sources** → your provider → **June / July / August** rows should show new files; Perspectives update within a few minutes.

**Note:** Re-uploading the same file/period may hit duplicate-import errors; use new files or delete the prior file in UI before retesting.

## Prerequisites

- Feature flag `CCM_EXTERNAL_DATA_INGESTION` enabled on the account
- At least one **External Cost Data Source** created in CACM UI
