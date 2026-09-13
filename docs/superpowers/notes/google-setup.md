# Google OAuth Setup & Dedicated Calendar

This document guides you through the one-time setup required to grant MagicBooking Calendar Sync access to your Google Calendar. You will perform this setup locally in your own browser — Claude cannot complete this step for you.

## Prerequisites

- A Google account
- `google-auth-oauthlib>=1.2` installed via `pip install -e ".[dev]"`

## Step 1: Create a Google Cloud OAuth Client

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one) for this application
3. Enable the "Google Calendar API":
   - In the left sidebar, click **APIs & Services** > **Library**
   - Search for "Google Calendar API"
   - Click the result and press **Enable**
4. Create an OAuth 2.0 client credential:
   - Go to **APIs & Services** > **Credentials**
   - Click **Create Credentials** > **OAuth client ID**
   - Choose **Desktop app** as the application type
   - Click **Create**
5. Download or copy the credentials:
   - A dialog will appear with your `Client ID` and `Client Secret`
   - Save these values in your password manager or a secure local file — you will need them in Step 3
6. Configure the OAuth consent screen (optional, but recommended):
   - Go to **APIs & Services** > **OAuth consent screen**
   - Click **Edit App** and ensure your Google account is listed as a test user
   - This allows you to use the app without publishing it

## Step 2: Run the OAuth Setup Script

The script is ready to use. When you run it, it will:
1. Open your default web browser to Google's consent screen
2. Ask you to approve access to your Google Calendar
3. Print a refresh token (which you will store in AWS SSM in Task 9)

Run this command in your terminal:

```bash
cd /path/to/magicbooking-calendar-sync
pip install -e ".[dev]"
python3 scripts/google_oauth_setup.py \
  --client-id YOUR_CLIENT_ID_HERE \
  --client-secret YOUR_CLIENT_SECRET_HERE
```

Replace `YOUR_CLIENT_ID_HERE` and `YOUR_CLIENT_SECRET_HERE` with the values from Step 1.

When the script runs:
- Your default browser will open to Google's login page
- You may be asked to grant permission — click **Allow**
- After approval, a page may show an error (this is expected — just close it)
- The script will print three values to your terminal:
  - `google/oauth_client_id`
  - `google/oauth_client_secret`
  - `google/oauth_refresh_token`

**Important:** Copy these printed values somewhere safe (e.g., your password manager). Do **not** commit them to the repository. You will transfer them to AWS SSM in Task 9.

## Step 3: Create a Dedicated Calendar

1. Open [Google Calendar](https://calendar.google.com/)
2. In the left sidebar, click the **+** next to "Other calendars"
3. Choose **Create new calendar**
4. Enter a name (e.g., "Hurst Primary Club Bookings")
5. Leave other settings as default and click **Create calendar**
6. Once created, open the calendar's settings:
   - Click the three-dot menu next to the calendar name
   - Select **Settings**
7. Scroll to **Integrate calendar** and copy the **Calendar ID** (looks like `xxxxx@group.calendar.google.com`)

Store this Calendar ID with your OAuth credentials in your password manager — you will add it to SSM in Task 9.

## What to Do Next

**Do not proceed until:**
- The setup script ran successfully and printed the refresh token
- You have created a dedicated Google Calendar
- You have saved all three values (client ID, client secret, refresh token) and the calendar ID securely

**Next step:** Follow Task 9 to store these values in AWS SSM.

## Verification

To verify your setup works:
1. Confirm the script ran without errors
2. Confirm you received a refresh token (it should be a long string starting with `1//...`)
3. Confirm the dedicated calendar exists and has a Calendar ID

## Troubleshooting

**Script fails with "invalid client":**
- Double-check your client ID and secret — they must match exactly what Google provided
- Ensure the OAuth consent screen includes your email as a test user

**Browser doesn't open:**
- The script defaults to opening your system's default browser
- You can manually visit the URL printed in the terminal if needed

**Redirect localhost error:**
- This is expected if the browser lands on `http://localhost` after consent
- The script has already captured the token by this point — you can close the browser
