locals {
  ssm_secret_names = [
    "magicbooking/username",
    "magicbooking/password",
    "google/oauth_client_id",
    "google/oauth_client_secret",
    "google/oauth_refresh_token",
    "google/calendar_id",
  ]
}

resource "aws_ssm_parameter" "secrets" {
  for_each = toset(local.ssm_secret_names)

  name  = "/magicbooking-calendar-sync/${each.value}"
  type  = "SecureString"
  value = "placeholder-set-out-of-band"

  lifecycle {
    ignore_changes = [value]
  }
}
