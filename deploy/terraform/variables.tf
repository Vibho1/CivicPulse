variable "project_id" {
  description = "Google Cloud project ID to deploy into."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, the buckets and the image registry."
  type        = string
  default     = "asia-south1"
}

variable "service_name" {
  description = "Cloud Run service name; also prefixes the registry, buckets and service accounts."
  type        = string
  default     = "civicpulse"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,18}[a-z0-9]$", var.service_name))
    error_message = "Use 4-20 lowercase letters, digits or dashes (it prefixes service-account IDs, which are limited to 30 characters)."
  }
}

variable "deployer_service_account" {
  description = "Optional service-account email that Terraform impersonates instead of using your own credentials."
  type        = string
  default     = ""
}

variable "gemini_backend" {
  description = "How the API calls Gemini: vertex (runtime service account, no key), apikey (Secret Manager secret) or off (offline heuristics)."
  type        = string
  default     = "vertex"

  validation {
    condition     = contains(["vertex", "apikey", "off"], var.gemini_backend)
    error_message = "gemini_backend must be one of: vertex, apikey, off."
  }
}

variable "gemini_model" {
  description = "Gemini model ID (gemini-2.5-flash is no longer served to new Vertex AI projects)."
  type        = string
  default     = "gemini-3.8-flash"
}

variable "vertex_location" {
  description = "Vertex AI location for Gemini calls."
  type        = string
  default     = "global"
}

variable "gemini_api_key_secret" {
  description = "Existing Secret Manager secret ID holding a Gemini API key (only used when gemini_backend = \"apikey\")."
  type        = string
  default     = ""
}

variable "public" {
  description = "true: anyone with the URL can use the app (invoker IAM check disabled, which also works under domain-restricted sharing). false: only `invokers`."
  type        = bool
  default     = true
}

variable "invokers" {
  description = "Principals allowed to call the service when public = false, e.g. [\"user:alice@example.com\", \"group:team@example.com\"]."
  type        = list(string)
  default     = []
}

variable "demo_mode" {
  description = "Expose the Demo menu (/api/admin/seed and /api/admin/reset): anyone with the URL could then wipe the data."
  type        = bool
  default     = false
}

variable "min_instances" {
  description = "1 removes cold starts but the idle instance is billed; 0 scales to zero."
  type        = number
  default     = 0

  validation {
    condition     = contains([0, 1], var.min_instances)
    error_message = "min_instances must be 0 or 1 (the service runs a single SQLite writer)."
  }
}

variable "extra_env" {
  description = "Extra environment variables for the API, e.g. { DUPLICATE_WINDOW_S = \"0\" }."
  type        = map(string)
  default     = {}
}

variable "force_destroy_buckets" {
  description = "Let `terraform destroy` delete the data bucket even if it still holds photos, voice notes and the database replica."
  type        = bool
  default     = true
}

variable "public_base_url" {
  description = "Public URL of the app (e.g. the service_url output or a custom domain). Used in WhatsApp replies; escalation drafts fall back to the request's own URL. Empty = unset."
  type        = string
  default     = ""
}

variable "public_audio" {
  description = "Serve citizens' voice notes publicly on issue pages. Off by default (voice can identify a person); the reporter always gets their own playback."
  type        = bool
  default     = false
}

# WhatsApp Cloud API intake (docs/WHATSAPP.md). Create the three secrets yourself (gcloud secrets create ...),
# add their values, then put the secret IDs here; Terraform only grants the runtime account access.
variable "whatsapp_verify_token_secret" {
  description = "Existing Secret Manager secret ID with the webhook verify token. Empty = WhatsApp intake off."
  type        = string
  default     = ""
}

variable "whatsapp_app_secret_secret" {
  description = "Existing Secret Manager secret ID with the Meta app secret (verifies X-Hub-Signature-256)."
  type        = string
  default     = ""
}

variable "whatsapp_access_token_secret" {
  description = "Existing Secret Manager secret ID with the WhatsApp Cloud API access token."
  type        = string
  default     = ""
}

variable "whatsapp_phone_number_id" {
  description = "WhatsApp Cloud API phone number ID (not secret)."
  type        = string
  default     = ""
}
