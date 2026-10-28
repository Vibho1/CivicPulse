# Deploying CivicPulse to Google Cloud (Terraform + Cloud Run)

One container serves both the PWA and the API. The infrastructure is Terraform in
[`deploy/terraform`](../deploy/terraform). Images are built by Cloud Build from
[`deploy/cloudbuild.yaml`](../deploy/cloudbuild.yaml) and rolled out with one `gcloud` command.

```
Browser ──HTTPS──► Cloud Run service "civicpulse"  (1 instance)
                    ├─ FastAPI + built PWA (uvicorn :8080)
                    ├─ SQLite on local disk ──Litestream──► gs://<project>-civicpulse-data/db/
                    ├─ /mnt/gcs (Cloud Storage volume) ───► gs://<project>-civicpulse-data/uploads/
                    └─ Gemini on Vertex AI (runtime service account, no API key)
```

**What Terraform creates.** Nothing is hard-coded to a project.

| Resource | Purpose |
| --- | --- |
| APIs: Run, Cloud Build, Artifact Registry, Storage, IAM, Resource Manager, Vertex AI | Left enabled on destroy |
| Artifact Registry repo `civicpulse` | Images; keeps the last 5, deletes anything older than 14 days |
| Bucket `<project>-civicpulse-data` | Photos and voice notes, plus the Litestream database replica. Private. |
| Bucket `<project>-civicpulse-build` | Cloud Build source uploads, deleted after 7 days |
| Service account `civicpulse-build` | Write logs, read the build bucket, push to the repo |
| Service account `civicpulse-run` | Read/write the data bucket, call Vertex AI |
| Cloud Run service `civicpulse` | gen2, 1 vCPU / 1 GiB, CPU always on, max 1 instance, bucket mounted at `/mnt/gcs` |

## Steps

### 0. Prerequisites

- A Google Cloud project with billing enabled.
- The `gcloud` CLI and Terraform ≥ 1.5. [Cloud Shell](https://shell.cloud.google.com) has both.
- An identity that may create the resources above: project Owner, or the roles listed under
  *Optional: deploy as a service account* below.

### 1. Sign in with the identity you want to deploy as

```bash
gcloud auth login                         # used by the gcloud build/rollout commands
gcloud auth application-default login     # used by Terraform
```

To keep your personal account out of it, see *Optional: deploy as a service account* below.

### 2. Configure

```bash
cd CivicPulse/deploy/terraform
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars: set project_id = "<your-project-id>" (everything else has defaults)
```

### 3. Create the infrastructure

```bash
terraform init
terraform validate
terraform plan        # review: ~20 resources to add, nothing to change or destroy
terraform apply
```

The first apply takes a few minutes. It starts the service on Google's public *hello* placeholder
image, so `terraform output service_url` already responds.

### 4. Build the app image and roll it out

```bash
terraform output -raw release_commands    # prints the exact commands for your project
cd ../..                                  # run them from the repository root
```

They look like this (≈4–6 minutes for the build):

```bash
IMAGE=asia-south1-docker.pkg.dev/<project>/civicpulse/civicpulse:$(date +%Y%m%d-%H%M%S)
gcloud builds submit . --project <project> --config deploy/cloudbuild.yaml \
  --substitutions _IMAGE=$IMAGE \
  --service-account projects/<project>/serviceAccounts/civicpulse-build@<project>.iam.gserviceaccount.com \
  --gcs-source-staging-dir gs://<project>-civicpulse-build/source
gcloud run services update civicpulse --project <project> --region asia-south1 --image $IMAGE
```

### 5. Check it

```bash
URL=$(terraform -chdir=deploy/terraform output -raw service_url)
curl -s "$URL/api/health"     # expect "ai_mode": "gemini" and non-zero counts
```

Open the URL. The map shows the Bengaluru demo story, which loads on first boot, and the header
pill says **Gemini live**.

Then set `public_base_url` to that URL in `terraform.tfvars` and `terraform apply` once more, so media
links and WhatsApp replies use it.

To confirm report parsing meets the PRD's 5-second target with your model, run the probe locally with
your own credentials (it prints the timing): `cd backend && GEMINI_USE_VERTEX=true
GOOGLE_CLOUD_PROJECT=<project> GEMINI_MODEL=gemini-3.8-flash .venv/bin/python scripts/ai_probe.py`.

### Later

- **New code:** repeat step 4.
- **Infrastructure or config changes:** edit `terraform.tfvars`, then `terraform apply`. Terraform
  ignores the image, so it never rolls back a release.
- **Logs:** `gcloud run services logs read civicpulse --project <project> --region asia-south1 --limit 100`.

Useful settings in `terraform.tfvars`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `region` | `asia-south1` | Mumbai, closest to Bengaluru |
| `gemini_backend` | `vertex` | `vertex`, `apikey` (with `gemini_api_key_secret`) or `off` |
| `gemini_model` | `gemini-3.8-flash` | `gemini-2.5-flash` returns 404 on Vertex AI for new projects |
| `public` | `true` | `false` + `invokers = ["user:you@example.com"]` makes the service private |
| `demo_mode` | `false` | `true` shows the Demo menu: **anyone** with the URL can seed/reset the data |
| `min_instances` | `0` | `1` removes cold starts (billed while idle). Handy on judging day. |
| `public_base_url` | `""` | The app's public URL (set it after the first apply) |
| `public_audio` | `false` | `true` shows citizens' voice notes on public issue pages |
| `whatsapp_*` | `""` | WhatsApp intake: three Secret Manager secret IDs + phone number ID ([WHATSAPP.md](WHATSAPP.md)) |
| `extra_env` | `{}` | e.g. `{ DUPLICATE_WINDOW_S = "0" }` for rehearsals |

### Tear everything down

```bash
cd CivicPulse/deploy/terraform
terraform destroy
```

This removes the service, both buckets (including data, because `force_destroy_buckets = true`),
the repo and its images, both service accounts and their IAM bindings. The APIs stay enabled; they
cost nothing.

## Optional: deploy as a service account

Use this so that infrastructure changes are made by a dedicated identity instead of your own
account. A project Owner runs this once:

```bash
PROJECT_ID=<your-project-id>
gcloud iam service-accounts create terraform-deployer --project $PROJECT_ID --display-name "Terraform deployer"
SA=terraform-deployer@$PROJECT_ID.iam.gserviceaccount.com
for role in roles/serviceusage.serviceUsageAdmin roles/artifactregistry.admin roles/storage.admin \
            roles/iam.serviceAccountAdmin roles/iam.serviceAccountUser roles/resourcemanager.projectIamAdmin \
            roles/run.admin roles/cloudbuild.builds.editor; do
  gcloud projects add-iam-policy-binding $PROJECT_ID --member serviceAccount:$SA --role $role --condition None
done
# allow a person (or CI) to impersonate it
gcloud iam service-accounts add-iam-policy-binding $SA --project $PROJECT_ID \
  --member user:<you@example.com> --role roles/iam.serviceAccountTokenCreator
```

Then:

- **Terraform:** set `deployer_service_account = "terraform-deployer@<project>.iam.gserviceaccount.com"`
  in `terraform.tfvars`.
- **gcloud (step 4):** run `gcloud config set auth/impersonate_service_account terraform-deployer@<project>.iam.gserviceaccount.com`.
  Undo it afterwards with `gcloud config unset auth/impersonate_service_account`.
- **API-key mode** additionally needs `roles/secretmanager.admin`.

## How data is kept

- **Database:** SQLite runs on the instance's local disk. On a cold start
  [Litestream](https://litestream.io) restores the latest copy from `gs://<bucket>/db/`. While the
  API runs it streams every change back within about a second, with a final sync when Cloud Run
  stops the instance. That's why the service is capped at **one instance**: SQLite has a single
  writer. CPU stays allocated so replication is never starved.
- **Photos and voice notes:** written straight into the bucket through the `/mnt/gcs` volume and
  served by the API at `/uploads/...` (the bucket itself stays private).
- **Releases:** for a few seconds the old and new revisions overlap. Avoid filing reports during a
  rollout.
- **Start over:** set `demo_mode = true`, apply, then use *Demo → Reset*. Or delete
  `gs://<bucket>/db` and `gs://<bucket>/uploads`, then roll out again; the demo story reloads on boot.

## Rough costs

- **Cloud Run:** about $0.07–0.10 per hour while the instance is up (1 vCPU / 1 GiB, CPU always on).
  With `min_instances = 0` it shuts down after ~15 idle minutes, so light demo use costs a few
  dollars a month. `min_instances = 1` costs roughly $50–75 a month.
  See [Cloud Run pricing](https://cloud.google.com/run/pricing).
- **Cloud Storage, Artifact Registry, Cloud Build:** cents.
- **Gemini on Vertex AI:** a fraction of a cent per report or verification.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `terraform validate` rejects `invoker_iam_disabled` or `gcs` | The Google provider is too old. Run `terraform init -upgrade`. |
| First apply fails: Cloud Run revision not ready, or a bucket permission error | IAM grants can take a minute to propagate. Run `terraform apply` again. |
| `allUsers` / "do not belong to a permitted customer" | Domain-restricted sharing. `public = true` uses `invoker_iam_disabled`, which avoids `allUsers`. If the org also enforces `run.managed.requireInvokerIam`, use `public = false` with `invokers`. |
| "API requires a quota project" with user credentials | Run `gcloud auth application-default set-quota-project <project>`. The provider already bills calls to `project_id`. |
| Cloud Build: permission denied on the source or the push | Make sure you passed `--service-account` and `--gcs-source-staging-dir` from `release_commands`, then retry after a minute. |
| `/api/health` shows `"ai_mode": "heuristic"` | Check that `aiplatform.googleapis.com` is enabled and that `civicpulse-run` has `roles/aiplatform.user`. Look for "Could not initialise Gemini" in the logs. |
| Reports fall back to heuristic (`404 NOT_FOUND` in the logs) | The model isn't available to the project. Change `gemini_model` and apply. |

Test Vertex mode locally: run `gcloud auth application-default login`, then add
`GEMINI_USE_VERTEX=true`, `GOOGLE_CLOUD_PROJECT=<project>` and `GEMINI_MODEL=gemini-3.8-flash` to
`.env`, then run `cd backend && .venv/bin/python -m scripts.ai_probe`.
