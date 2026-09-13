# magicbooking-calendar-sync

Daily sync of MagicBooking (hurstprimary.magicbooking.co.uk) booked
sessions into a dedicated Google Calendar. See
`docs/superpowers/specs/2026-09-13-magicbooking-calendar-sync-design.md`
for the design and
`docs/superpowers/plans/2026-09-13-magicbooking-calendar-sync.md` for how
it was built.

## Deploy

1. Build the Lambda package:
   ```bash
   ./scripts/build_lambda.sh
   ```
2. Provision infrastructure:
   ```bash
   cd infra
   terraform init
   terraform apply -var="alert_email=you@example.com"
   ```
3. Populate real secret values (placeholders were created by Terraform
   but ignored on subsequent applies):
   ```bash
   aws ssm put-parameter --name /magicbooking-calendar-sync/magicbooking/username --type SecureString --overwrite --value "..."
   aws ssm put-parameter --name /magicbooking-calendar-sync/magicbooking/password --type SecureString --overwrite --value "..."
   aws ssm put-parameter --name /magicbooking-calendar-sync/google/oauth_client_id --type SecureString --overwrite --value "..."
   aws ssm put-parameter --name /magicbooking-calendar-sync/google/oauth_client_secret --type SecureString --overwrite --value "..."
   aws ssm put-parameter --name /magicbooking-calendar-sync/google/oauth_refresh_token --type SecureString --overwrite --value "..."
   aws ssm put-parameter --name /magicbooking-calendar-sync/google/calendar_id --type SecureString --overwrite --value "..."
   ```
   (Get the Google values by running `scripts/google_oauth_setup.py` — see
   `docs/superpowers/notes/google-setup.md`.)
4. Confirm the SNS email subscription (check your inbox for a confirmation
   link from AWS after `terraform apply`).

## Run

Runs automatically daily via EventBridge Scheduler. To trigger manually:
```bash
aws lambda invoke --function-name magicbooking-calendar-sync /tmp/out.json && cat /tmp/out.json
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```
