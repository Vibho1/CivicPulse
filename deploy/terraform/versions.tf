terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.20"
    }
  }

  # Optional: keep state in a Cloud Storage bucket you created beforehand (recommended for teams):
  # backend "gcs" {
  #   bucket = "<your-terraform-state-bucket>"
  #   prefix = "civicpulse"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region

  # Bill API calls to the target project; needed when running with user credentials (ADC).
  billing_project       = var.project_id
  user_project_override = true

  # Optionally run as a deployer service account instead of your own identity.
  impersonate_service_account = var.deployer_service_account == "" ? null : var.deployer_service_account
}
