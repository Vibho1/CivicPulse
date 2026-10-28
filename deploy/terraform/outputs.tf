output "service_url" {
  description = "URL of the app."
  value       = google_cloud_run_v2_service.app.uri
}

output "whatsapp_webhook_url" {
  description = "Callback URL for the Meta app's WhatsApp webhook (only used when WhatsApp intake is configured)."
  value       = local.whatsapp_enabled ? "${google_cloud_run_v2_service.app.uri}/api/whatsapp/webhook" : null
}

output "project_id" {
  value = var.project_id
}

output "region" {
  value = var.region
}

output "image_repository" {
  description = "Artifact Registry path for CivicPulse images."
  value       = local.image_repo
}

output "build_service_account" {
  description = "Value for `gcloud builds submit --service-account`."
  value       = google_service_account.build.id
}

output "build_bucket" {
  description = "Staging bucket for Cloud Build source uploads."
  value       = google_storage_bucket.build.name
}

output "data_bucket" {
  description = "Bucket holding uploads and the Litestream database replica."
  value       = google_storage_bucket.data.name
}

output "release_commands" {
  description = "Build the image with Cloud Build and roll it out. Run from the repository root."
  value       = <<-EOT
    IMAGE=${local.image_repo}/${var.service_name}:$(date +%Y%m%d-%H%M%S)
    gcloud builds submit . --project ${var.project_id} --config deploy/cloudbuild.yaml \
      --substitutions _IMAGE=$IMAGE \
      --service-account ${google_service_account.build.id} \
      --gcs-source-staging-dir gs://${google_storage_bucket.build.name}/source
    gcloud run services update ${google_cloud_run_v2_service.app.name} --project ${var.project_id} --region ${var.region} --image $IMAGE
  EOT
}
