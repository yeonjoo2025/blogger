"""Run once locally to create a real token.json for Blogger API."""

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/blogger"]
TOKEN_PATH = Path("token.json")


def find_client_secret() -> Path:
    candidates = [
        Path("client_secret.json"),
        *sorted(Path(".").glob("client_secret_*.apps.googleusercontent.com.json")),
    ]
    for path in candidates:
        if path.exists():
            return path
    raise SystemExit("Missing client_secret*.json in the current directory.")


def main() -> None:
    client_secret = find_client_secret()
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"Saved OAuth token to {TOKEN_PATH.resolve()}")
    print("Do not commit this file. Add it as a Cloud Agent secret.")


if __name__ == "__main__":
    main()
