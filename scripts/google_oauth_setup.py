"""One-time, interactive script: run locally to grant this project access
to your Google Calendar and print a refresh token to store in SSM.

Usage:
    python3 scripts/google_oauth_setup.py --client-id ... --client-secret ...
"""
import argparse

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    args = parser.parse_args()

    client_config = {
        "installed": {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    credentials = flow.run_local_server(port=0)

    print("\nSUCCESS. Store these values in SSM (see Task 9):\n")
    print(f"  google/oauth_client_id     = {args.client_id}")
    print(f"  google/oauth_client_secret = {args.client_secret}")
    print(f"  google/oauth_refresh_token = {credentials.refresh_token}")


if __name__ == "__main__":
    main()
