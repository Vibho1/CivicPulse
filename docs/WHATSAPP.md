# WhatsApp intake (optional)

Citizens can report from WhatsApp instead of the PWA (PRD: "PWA or WhatsApp webhook", OQ-1). CivicPulse
receives messages through the [WhatsApp Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api)
webhook and files them through the same pipeline as the PWA (Gemini parsing, agency routing, clustering,
anti-spam). The feature is **off** unless `WHATSAPP_VERIFY_TOKEN` is set. Until then,
`/api/whatsapp/webhook` answers 404.

## How citizens use it

1. Message the CivicPulse number with a **voice note** (any language, up to 30 s), a **photo** and/or a
   **short description**.
2. **Share the location**: tap 📎 (Android) or **+** (iPhone) → **Location** → **Send your current location**.
   Either step can come first.
3. When the location and at least one piece of evidence have arrived, CivicPulse files the report and
   replies with:
   - the tracking ID (e.g. `CP-7KQ2MD`) and whether it's a new issue or joined an existing one
   - the category and severity
   - the responsible agency, plus a second agency if one shares responsibility
   - a link to the issue page (when `PUBLIC_BASE_URL` is set)

Other replies:

| Situation | Reply |
| --- | --- |
| Evidence but no location yet | Asks for the location (once per burst of messages) |
| Location but no evidence yet | Asks for a voice note, photo or text |
| `hi` / `help` / `namaskara`, or the citizen opens the chat for the first time | How-to message |
| `cancel` | Discards the draft |
| Same person, same kind of issue, within 1 km / 5 min | "You already reported this … (CP-…)" |
| Not a civic issue / unclear | Asks for a clearer photo or description; the location is kept |
| Voice note too long, photo too large or not JPEG/PNG/WebP | Explains the limit; asks to send it again |
| Model flags an emergency | Adds "call 112 now; CivicPulse does not dispatch emergency services" |
| Stickers, videos, contacts, live location… | Polite "I can only read …" |

An unfinished draft expires after **30 minutes** of inactivity.

## Setup

### 1. Meta app and test number

1. Go to [developers.facebook.com/apps](https://developers.facebook.com/apps) → **Create app** → **Business**
   type (or the "Connect with customers through WhatsApp" use case). Add the **WhatsApp** product.
2. Open **WhatsApp → API Setup**. Meta gives you a free test number. Note its **Phone number ID**: the
   numeric ID, not the phone number. Under **To**, add and verify the phones you'll test from. A test number
   can only message up to 5 verified recipients.
3. **Access token.** The token on the API Setup page expires after 24 h. For anything longer-lived, go to
   Business settings → **System users** → add one. Assign it the app and the WhatsApp account. Generate a
   token with `whatsapp_business_messaging` (and `whatsapp_business_management`).
4. **App secret.** Find it under App settings → **Basic** → App secret.

### 2. Configure CivicPulse

| Variable | Value |
| --- | --- |
| `WHATSAPP_VERIFY_TOKEN` | Any random string you choose; it turns the feature on. `python -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `WHATSAPP_APP_SECRET` | The app secret. It verifies `X-Hub-Signature-256` on every webhook call and salts the phone-number hashes. **Required in production.** |
| `WHATSAPP_ACCESS_TOKEN` | Token from step 1.3. Used to download photos and voice notes and to send replies. |
| `WHATSAPP_PHONE_NUMBER_ID` | Phone number ID from step 1.2. Replies come from this number, and messages addressed to other numbers on the same app are ignored. |
| `WHATSAPP_GRAPH_VERSION` | Optional, default `v21.0` |
| `PUBLIC_BASE_URL` | e.g. `https://civicpulse-xyz.a.run.app`. Adds the issue link to replies. |

Locally, put these in `.env`. **On Cloud Run**, keep the verify token, app secret and access token in
**Secret Manager**. Never put them in `terraform.tfvars`, the image or a committed file. The phone
number ID isn't secret. With the Terraform in `deploy/terraform`:

```bash
gcloud services enable secretmanager.googleapis.com --project YOUR_PROJECT
for s in whatsapp-verify-token whatsapp-app-secret whatsapp-access-token; do
  gcloud secrets create "$s" --project YOUR_PROJECT --replication-policy automatic
done
printf %s "$VERIFY_TOKEN" | gcloud secrets versions add whatsapp-verify-token --project YOUR_PROJECT --data-file=-
printf %s "$APP_SECRET"   | gcloud secrets versions add whatsapp-app-secret   --project YOUR_PROJECT --data-file=-
printf %s "$ACCESS_TOKEN" | gcloud secrets versions add whatsapp-access-token --project YOUR_PROJECT --data-file=-
```

then set `whatsapp_verify_token_secret`, `whatsapp_app_secret_secret`, `whatsapp_access_token_secret`,
`whatsapp_phone_number_id` and `public_base_url` in `terraform.tfvars` (see `terraform.tfvars.example`)
and run `terraform apply`. Terraform grants the service's runtime account access to the three secrets
and passes them in as environment variables; the `whatsapp_webhook_url` output is the callback URL.

### 3. Register the webhook

In **WhatsApp → Configuration → Webhook → Edit**:

- **Callback URL:** `https://<service-url>/api/whatsapp/webhook`
- **Verify token:** the value of `WHATSAPP_VERIFY_TOKEN`

Click **Verify and save**: Meta sends `GET …?hub.mode=subscribe&hub.verify_token=…&hub.challenge=…` and
CivicPulse echoes the challenge. Then, under **Webhook fields**, subscribe to **`messages`**.

Meta must reach the URL over public HTTPS. On Cloud Run that means `public = true`; an IAM-protected
service can't receive webhooks. For local development, use a tunnel, e.g.
`cloudflared tunnel --url http://localhost:8000`.

### 4. Try it

From a verified phone, send `hi` to the test number. You get the how-to message. Then send a voice note
and your location, and the ticket reply comes back within a few seconds.

To exercise the webhook without Meta, sign a sample delivery yourself. Replies then fail and are only
logged, unless a real token is configured.

```bash
BODY='{"object":"whatsapp_business_account","entry":[{"id":"0","changes":[{"field":"messages","value":{"metadata":{"phone_number_id":"'$WHATSAPP_PHONE_NUMBER_ID'"},"messages":[{"from":"15550000000","id":"wamid.local1","type":"text","text":{"body":"Big pothole near the bus stop"}}]}}]}]}'
SIG=$(printf %s "$BODY" | openssl dgst -sha256 -hmac "$WHATSAPP_APP_SECRET" | sed 's/^.* //')
curl -s localhost:8000/api/whatsapp/webhook -H 'Content-Type: application/json' -H "X-Hub-Signature-256: sha256=$SIG" -d "$BODY"
```

## Privacy

- **Phone numbers are never stored or logged.** A sender is known only as `wa:` + the first 16 hex
  characters of SHA-256(app secret + number). This is the report's `reporter_id`. The anti-spam rule and
  the "unique reporters" count work on it like any other reporter ID.
- WhatsApp message IDs embed the sender's number, so only salted hashes of them are kept, for 7 days, to
  ignore Meta's redeliveries. Profile names aren't stored.
- A draft holds the text, the WhatsApp media IDs and the location. It's deleted when the report is filed
  or after 30 minutes. Photos and voice notes are downloaded only when the report is complete, then stored
  like PWA uploads (photos are re-encoded without EXIF).
- Changing `WHATSAPP_APP_SECRET` gives every sender a new pseudonymous ID. Without an app secret, the
  verify token is the salt. Meta sends the verify token in a URL, so it can end up in access logs. That's
  one more reason to set the app secret.

## Behaviour and limits

- Same limits as the PWA: photo ≤ `MAX_IMAGE_MB` (JPEG/PNG/WebP), voice note ≤ `MAX_AUDIO_S` (+1.5 s
  tolerance) and ≤ `MAX_AUDIO_MB`, and the duplicate rule (`DUPLICATE_WINDOW_S` / `DUPLICATE_RADIUS_M`).
  Voice notes arrive as OGG/Opus. Their length is measured with `ffprobe`, which the Docker image includes.
  Without it, the duration isn't checked.
- The webhook answers 200 immediately and does the work (media download, Gemini, reply) in a background
  task, so Meta never retries because of a slow response. Messages from one sender are handled in order.
- Without `WHATSAPP_APP_SECRET`, unsigned calls are accepted (a warning is logged). Use that only for local
  development: anyone who knows the URL could file reports and trigger replies.
- Replies are free-form text. WhatsApp allows these within 24 h of the citizen's last message.
  CivicPulse never starts a conversation, so no message templates are needed. As a result, the "send a
  proof photo" requests after an official closure reach WhatsApp reporters only in the in-app inbox:
  CivicPulse deliberately keeps no number to message them later.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Meta: "The callback URL or verify token couldn't be validated" | A 404 means `WHATSAPP_VERIFY_TOKEN` isn't set on the service; a 403 means it doesn't match. Also check the URL ends in `/api/whatsapp/webhook` and that the service is public. |
| Webhook calls get 401 | `WHATSAPP_APP_SECRET` doesn't match the app's secret. |
| Messages are logged (`WhatsApp: 'text' message from wa:…`) but nothing comes back | The access token expired (temporary tokens last 24 h), `WHATSAPP_PHONE_NUMBER_ID` is wrong, or the sender isn't a verified recipient of the test number (Graph error 131030). Look for `WhatsApp reply failed` in the logs. |
| Citizens get "I couldn't download your photo / voice note" | The access token is missing, expired or lacks `whatsapp_business_messaging`. |
| No log line at all | The app isn't subscribed to the `messages` webhook field, or the message went to another number (`ignoring messages addressed to another business number`). |
