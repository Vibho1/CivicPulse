# CivicPulse on Cloud Run: one container (PWA + API), SQLite kept in Cloud Storage via Litestream,
# uploads on a Cloud Storage volume, Gemini via Vertex AI with the service's own identity.
#
# Terraform owns the infrastructure and configuration. Container images are built by Cloud Build
# and rolled out with `gcloud run services update --image` (see the release_commands output), so
# the first apply starts the service on Google's public "hello" placeholder image.

locals {
  labels         = { app = var.service_name, managed-by = "terraform" }
  data_bucket    = "${var.project_id}-${var.service_name}-data"
  build_bucket   = "${var.project_id}-${var.service_name}-build"
  image_repo     = "${var.region}-docker.pkg.dev/${var.project_id}/${var.service_name}"
  placeholder    = "us-docker.pkg.dev/cloudrun/container/hello"
  replica_prefix = "db/civicpulse.db"

  # WhatsApp Cloud API secrets: env var name -> existing Secret Manager secret ID.
  whatsapp_secrets = {
    for name, secret in {
      WHATSAPP_VERIFY_TOKEN = var.whatsapp_verify_token_secret
      WHATSAPP_APP_SECRET   = var.whatsapp_app_secret_secret
      WHATSAPP_ACCESS_TOKEN = var.whatsapp_access_token_secret
    } : name => secret if secret != ""
  }
  whatsapp_enabled = var.whatsapp_verify_token_secret != ""
  uses_secrets     = var.gemini_backend == "apikey" || length(local.whatsapp_secrets) > 0

  apis = toset(concat(
    [
      "run.googleapis.com",
      "cloudbuild.googleapis.com",
      "artifactregistry.googleapis.com",
      "storage.googleapis.com",
      "iam.googleapis.com",
      "cloudresourcemanager.googleapis.com",
      "serviceusage.googleapis.com",
    ],
    var.gemini_backend == "vertex" ? ["aiplatform.googleapis.com"] : [],
    local.uses_secrets ? ["secretmanager.googleapis.com"] : [],
  ))

  app_env = merge(
    {
      UPLOADS_DIR            = "/mnt/gcs/uploads"
      LITESTREAM_REPLICA_URL = "gcs://${local.data_bucket}/${local.replica_prefix}"
      SEED_ON_STARTUP        = "true"
      DEMO_MODE              = tostring(var.demo_mode)
      GEMINI_MODEL           = var.gemini_model
      PUBLIC_AUDIO           = tostring(var.public_audio)
    },
    var.gemini_backend == "vertex" ? {
      GEMINI_USE_VERTEX     = "true"
      GOOGLE_CLOUD_PROJECT  = var.project_id
      GOOGLE_CLOUD_LOCATION = var.vertex_location
    } : {},
    var.public_base_url != "" ? { PUBLIC_BASE_URL = var.public_base_url } : {},
    var.whatsapp_phone_number_id != "" ? { WHATSAPP_PHONE_NUMBER_ID = var.whatsapp_phone_number_id } : {},
    var.extra_env,
  )
}

# --------------------------------------------------------------------------------------- APIs --

resource "google_project_service" "apis" {
  for_each = local.apis

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false # other workloads in the project may rely on them; they cost nothing idle
}

# ---------------------------------------------------------------------------------- Registry --

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = var.service_name
  format        = "DOCKER"
  description   = "CivicPulse container images"
  labels        = local.labels

  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 5
    }
  }
  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition {
      older_than = "1209600s" # 14 days
    }
  }

  depends_on = [google_project_service.apis]
}

# ------------------------------------------------------------------------------------ Storage --

# Uploaded photos/voice notes (mounted at /mnt/gcs) and the Litestream replica of the database.
resource "google_storage_bucket" "data" {
  project                     = var.project_id
  name                        = local.data_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy_buckets
  labels                      = local.labels

  depends_on = [google_project_service.apis]
}

# Source tarballs uploaded by `gcloud builds submit` (instead of the default <project>_cloudbuild bucket).
resource "google_storage_bucket" "build" {
  project                     = var.project_id
  name                        = local.build_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true
  labels                      = local.labels

  lifecycle_rule {
    condition {
      age = 7
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.apis]
}

# --------------------------------------------------------------------------- Service accounts --

resource "google_service_account" "run" {
  project      = var.project_id
  account_id   = "${var.service_name}-run"
  display_name = "CivicPulse Cloud Run runtime"

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "build" {
  project      = var.project_id
  account_id   = "${var.service_name}-build"
  display_name = "CivicPulse Cloud Build"

  depends_on = [google_project_service.apis]
}

# Build identity: write logs, read the uploaded source, push images to this repository only.
resource "google_project_iam_member" "build_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = google_service_account.build.member
}

resource "google_storage_bucket_iam_member" "build_source" {
  bucket = google_storage_bucket.build.name
  role   = "roles/storage.objectViewer"
  member = google_service_account.build.member
}

resource "google_artifact_registry_repository_iam_member" "build_push" {
  project    = var.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.build.member
}

# Runtime identity: read/write the data bucket, call Gemini.
resource "google_storage_bucket_iam_member" "run_data" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectUser"
  member = google_service_account.run.member
}

resource "google_project_iam_member" "run_vertex" {
  count = var.gemini_backend == "vertex" ? 1 : 0

  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = google_service_account.run.member
}

resource "google_secret_manager_secret_iam_member" "run_gemini_key" {
  count = var.gemini_backend == "apikey" ? 1 : 0

  project   = var.project_id
  secret_id = var.gemini_api_key_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.run.member

  lifecycle {
    precondition {
      condition     = var.gemini_api_key_secret != ""
      error_message = "Set gemini_api_key_secret to an existing Secret Manager secret ID when gemini_backend = \"apikey\"."
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "run_whatsapp" {
  for_each = toset(values(local.whatsapp_secrets))

  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.run.member

  lifecycle {
    precondition {
      condition     = !local.whatsapp_enabled || (length(local.whatsapp_secrets) == 3 && var.whatsapp_phone_number_id != "")
      error_message = "WhatsApp intake needs all three secrets (verify token, app secret, access token) and whatsapp_phone_number_id."
    }
    precondition {
      condition     = !local.whatsapp_enabled || var.public
      error_message = "WhatsApp intake needs public = true: Meta must be able to call the webhook."
    }
  }

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------------- Cloud Run --

resource "google_cloud_run_v2_service" "app" {
  project              = var.project_id
  name                 = var.service_name
  location             = var.region
  ingress              = "INGRESS_TRAFFIC_ALL"
  invoker_iam_disabled = var.public
  deletion_protection  = false
  labels               = local.labels

  template {
    service_account                  = google_service_account.run.email
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"
    timeout                          = "300s"
    max_instance_request_concurrency = 40

    # One instance: SQLite has a single writer (Litestream replicates it to the data bucket).
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = 1
    }

    containers {
      image = local.placeholder

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = false # keep CPU allocated so Litestream replication is never starved
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.app_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.gemini_backend == "apikey" ? [var.gemini_api_key_secret] : []
        content {
          name = "GEMINI_API_KEY"
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      dynamic "env" {
        for_each = local.whatsapp_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = "data"
        mount_path = "/mnt/gcs"
      }
    }

    volumes {
      name = "data"
      gcs {
        bucket    = google_storage_bucket.data.name
        read_only = false
      }
    }
  }

  lifecycle {
    # Images are rolled out with `gcloud run services update --image` (release_commands output);
    # gcloud also stamps the client fields. Terraform owns everything else.
    ignore_changes = [
      client,
      client_version,
      template[0].containers[0].image,
    ]
  }

  depends_on = [
    google_project_service.apis,
    google_storage_bucket_iam_member.run_data,
    google_project_iam_member.run_vertex,
    google_secret_manager_secret_iam_member.run_gemini_key,
    google_secret_manager_secret_iam_member.run_whatsapp,
  ]
}

# Private mode: only these principals may call the service.
resource "google_cloud_run_v2_service_iam_member" "invokers" {
  for_each = var.public ? toset([]) : toset(var.invokers)

  project  = var.project_id
  location = google_cloud_run_v2_service.app.location
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = each.value
}
