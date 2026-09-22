# CACM External Cost Ingest (`external-data-ingestion-sync`)

Automates **FOCUS CSV** validation and upload to a Harness **External Cost Data Source** (Cloud & AI Cost Management).

**GitHub:** [Samriddha11/external-data-ingestion-sync](https://github.com/Samriddha11/external-data-ingestion-sync)

## What this does

1. **Cloud Auth Precheck** — detects `s3://` / `gs://` / Azure blob URIs, checks credentials and object access (AWS uses Harness secrets + boto3 if `aws` CLI is missing on the delegate).
2. **Transform → validate → ingest** — clones this repo on a K8s delegate, downloads the CSV from object storage, maps vendor columns to FOCUS, hard-validates, then calls CCM signed-url / filesinfo / dataingestion APIs.

| Piece | Location |
|--------|----------|
| Python CLI | `cacm_external_ingest/` |
| Pipeline (INLINE YAML you import) | `harness/pipeline.yaml` |
| Custom webhook trigger | `harness/trigger-webhook-s3-uri.yaml` |
| Monthly cron trigger (optional) | `harness/trigger-monthly-day5.yaml` |

---

## Install in your Harness account (customer guide)

Follow these steps in **your** account/org/project. Replace every placeholder (`YOUR_*`) with your values.

### Prerequisites

| Requirement | Notes |
|-------------|--------|
| Module | Cloud Cost Management (CCM) with **External Cost Data** enabled (`CCM_EXTERNAL_DATA_INGESTION` if gated) |
| External Cost Data Source | Create one under **Account Settings → Cloud Cost → Cloud Integrations → External Cost Data Sources**. Copy the provider UUID from the URL (`selectedProvider=...`, without `%22` quotes). |
| Harness API key | Project (or account) **Secret Text** — a PAT/SAT with permission to call CCM external-data APIs. |
| Kubernetes delegate | Healthy K8s delegate + **Environment** + **Infrastructure Definition** the Custom stage can use. Pod needs outbound HTTPS (Harness, GitHub, S3/GCS/Azure, and `astral.sh` if Python is bootstrapped via `uv`). |
| `git` on the delegate | Pipeline clones this repo by default. |
| Object storage | CSV(s) in S3, GCS, or Azure Blob (≤ **20 MB** each). |

### Step 1 — Create secrets

Create **Secret Text** secrets (Harness Secret Manager is fine). Identifiers below match `harness/pipeline.yaml`; rename in YAML if you prefer different IDs.

**Required — Harness API**

| Identifier | Value |
|------------|--------|
| `Sam-API-Key` | Your Harness PAT/SAT (or change the pipeline env var to your secret id) |

**Required for AWS S3** (account-scoped secrets use the `account.` prefix in the pipeline)

| Identifier | Value |
|------------|--------|
| `sam_aws_access_key_id` | Raw **20-character** Access Key ID only (`AKIA…` / `ASIA…`) — no quotes, no `export`, no newlines |
| `sam_aws_secret_access_key` | Secret access key only |
| `sam_aws_session_token` | STS session token if using temporary creds; omit/clear for long-lived IAM keys |

In the pipeline, refs are `account.sam_aws_*`. If you create secrets at **project** scope instead, change those refs to the bare identifier (drop `account.`).

**Optional — GCP / Azure** (wire as env vars on **Cloud Auth Precheck** when needed)

| Env var | Suggested secret id |
|---------|---------------------|
| `GCP_SA_JSON` | `gcp_sa_json` (full service account JSON) |
| `AZURE_STORAGE_CONNECTION_STRING` | `azure_storage_connection_string` |
| or | `azure_client_id` / `azure_client_secret` / `azure_tenant_id` |

### Step 2 — Import the pipeline

1. Open your project → **Pipelines** → **Create** → **Import from YAML** (or New Pipeline → YAML).
2. Paste the contents of [`harness/pipeline.yaml`](harness/pipeline.yaml).
3. Edit these fields for **your** account:

| YAML location | Change to |
|---------------|-----------|
| `projectIdentifier` / `orgIdentifier` | Your org and project |
| `environmentRef` (stage Ingest) | Your Environment identifier |
| `infrastructureDefinitions[].identifier` | Your Infra Definition identifier |
| `HARNESS_API_KEY` secret value | Your API key secret identifier |
| `AWS_*` secret values | Your AWS secret identifiers (with `account.` if account-scoped) |
| `AWS_DEFAULT_REGION` | Region of your bucket (e.g. `eu-north-1`, `us-east-1`) |

4. **Save**. Pipeline identifier should remain `cacm_external_cost_ingest` (or update triggers to match).

> The Custom stage does **not** deploy a service; it only needs the Environment/Infra so Harness can schedule ShellScript steps on your K8s delegate.

### Step 3 — Smoke test (manual Run)

**Pipeline Studio → Run** with:

| Input | Example |
|--------|---------|
| `provider_id` | Your External Cost Data Source UUID |
| `provider_type` | `snowflake` (or `custom` / `databricks`) |
| `object_uri_s3` | `s3://YOUR-BUCKET/path/file.csv` |
| `use_sample` | `false` |
| `validate_only` | `true` first |
| `derive_invoice_period_from_csv` | `true` (recommended) **or** set `invoice_period` |
| `git_repo_url` | leave default (this GitHub repo) unless you forked |
| `git_branch` | `main` |

Leave other URI / File Store / `repo_object_prefix*` fields empty unless you use them.

After Cloud Auth Precheck + validation succeed, re-run with `validate_only=false` to ingest.

**Invoice period tip:** CCM signed-url expects **day `01` on both bounds** (e.g. June → `20260601-20260701`). The pipeline normalizes calendar month-end inputs like `20260601-20260630` automatically.

### Step 4 — Custom webhook (pass S3 URI via curl)

1. Import or recreate [`harness/trigger-webhook-s3-uri.yaml`](harness/trigger-webhook-s3-uri.yaml):
   - Set `orgIdentifier`, `projectIdentifier`, `pipelineIdentifier`
   - Set `provider_id` in `inputYaml` to **your** provider UUID
2. **Pipelines → your pipeline → Triggers →** open **CACM S3 URI Webhook** → copy **Webhook URL**.

**Minimal curl:**

```bash
curl -X POST '$WEBHOOK_URL' \
  -H 'Content-Type: application/json' \
  -d '{
    "object_uri_s3": "s3://YOUR-BUCKET/path/monthly.csv"
  }'
```

**Optional JSON fields:**

```bash
curl -X POST '$WEBHOOK_URL' \
  -H 'Content-Type: application/json' \
  -d '{
    "object_uri_s3": "s3://YOUR-BUCKET/path/july.csv",
    "invoice_period": "20260701-20260801",
    "validate_only": "true"
  }'
```

| Payload field | Pipeline input |
|---------------|----------------|
| `object_uri_s3` | `object_uri_s3` (required) |
| `invoice_period` | optional |
| `validate_only` | `"true"` / `"false"` |

Defaults in the trigger YAML: `provider_type=snowflake`, `derive_invoice_period_from_csv=true`, `git_branch=main`.

### Step 5 — Optional monthly cron

Use [`harness/trigger-monthly-day5.yaml`](harness/trigger-monthly-day5.yaml) (UNIX cron `0 6 5 * *` UTC). Point `object_uri_s3` at a **stable** key your export job overwrites each month, and set your `provider_id`.

### Step 6 — Verify

**Account Settings → External Cost Data Sources →** your provider → confirm the month file appears. Perspectives update within a few minutes.

Re-uploading the same file/period can hit duplicate-import errors; use a new object or remove the prior file in the UI before retesting.

### Install checklist

- [ ] External Cost Data Source created; `provider_id` copied  
- [ ] API key + AWS (or GCP/Azure) secrets created; pipeline YAML refs updated  
- [ ] Environment + Infrastructure Definition point at a working K8s delegate  
- [ ] `AWS_DEFAULT_REGION` matches the bucket region  
- [ ] Manual Run with `validate_only=true` then `false`  
- [ ] Webhook trigger created; curl smoke test  
- [ ] (Optional) Cron trigger for monthly refresh  

---

## Pipeline stages

| Step | Purpose |
|------|---------|
| **Cloud Auth Precheck** | Allowlist URI; AWS STS + S3 head/list (boto3 bootstrap if needed); GCS/Azure equivalents |
| **Transform Validate Ingest** | `git clone` this repo → pip/uv deps → download CSV → FOCUS transform → validate → (optional) CCM ingest |

## Pipeline inputs

| Input | Description |
|--------|-------------|
| `provider_id` | External Cost Data Source UUID |
| `provider_type` | `custom`, `snowflake`, or `databricks` |
| `invoice_period` | `YYYYMMDD-YYYYMMDD` (normalized to day-01 bounds for the API when needed) |
| `derive_invoice_period_from_csv` | `true` to derive from `BillingPeriodStart` / `BillingPeriodEnd` |
| `object_uri` | Any cloud CSV (overrides `object_uri_*`) |
| `object_uri_s3` | `s3://bucket/path/file.csv` |
| `object_uri_gcs` | `gs://bucket/path/file.csv` |
| `object_uri_azure` | Azure HTTPS or `azure://account/container/file.csv` |
| `use_sample` | `true` → bundled `examples/sample_focus.csv` |
| `validate_only` | `true` → skip CCM ingest APIs |
| `git_repo_url` / `git_branch` | Source of the Python job (default: this GitHub repo / `main`) |
| `repo_object_prefix*` / `repo_path` | Alternate ways to supply job code (object storage or path on the image) |
| `file_store_ref` | Optional Harness File Store CSV (`july` / `august` shortcuts in the script) |

## Features

- Provider adapters: `custom`, `snowflake`, `databricks` → FOCUS  
- Hard validation: required columns, `ChargeCategory`, ISO dates, 20 MB limit  
- Multi-cloud download: S3 / GCS / Azure  
- Delegate-friendly: bootstraps Python via `uv` when `python3` is missing; AWS precheck via boto3 when `aws` CLI is missing  

## Local CLI

```bash
git clone https://github.com/Samriddha11/external-data-ingestion-sync.git
cd external-data-ingestion-sync
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export HARNESS_API_KEY="your-key"
python -m cacm_external_ingest.cli \
  --account-id YOUR_ACCOUNT_ID \
  --api-key "$HARNESS_API_KEY" \
  --provider-id YOUR_PROVIDER_UUID \
  --provider-type snowflake \
  --object-uri s3://YOUR-BUCKET/path/file.csv \
  --derive-invoice-period-from-csv \
  --validate-only
```

Remove `--validate-only` to ingest. Use `--object-uri` with `gs://` or Azure URLs the same way.

## Repo layout (Harness files)

```text
harness/
  pipeline.yaml                 # Main Custom-stage pipeline
  trigger-webhook-s3-uri.yaml   # Custom webhook (curl → object_uri_s3)
  trigger-monthly-day5.yaml     # Optional cron
  input-set-monthly-ingest.yaml # Optional input set
```

## Reference demo account (maintainers)

| Field | Value |
|--------|--------|
| Account ID | `SxuV0ChbRqWGSYClFlMQMQ` |
| Org / Project | `sam` / `CCMDemo` |
| Pipeline | `cacm_external_cost_ingest` |
| API secret | `Sam-API-Key` |
| AWS secrets | `account.sam_aws_access_key_id` / `_secret_access_key` / `_session_token` |
| Env / Infra | `k8ssamtest` / `lbgpock8s` |

Customers should **not** copy these IDs into their install — use Step 2 substitutions above.

## Prerequisites (summary)

- Feature flag / entitlement for external data ingest on the account  
- At least one **External Cost Data Source** in the CACM UI  
- Delegate that can reach Harness, GitHub (or your fork), and the object store  
