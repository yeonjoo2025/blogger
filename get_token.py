"""Run once locally to create a real token.json for Blogger API."""

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from blogger_auth import SCOPES, TOKEN_PATH, ensure_client_secret_file


def main() -> None:
    client_secret = ensure_client_secret_file()
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"Saved OAuth token to {TOKEN_PATH.resolve()}")
    print("Do not commit this file.")
    print(
        "Cloud Agents: Dashboard → Cloud Agents → Secrets (Personal)에 "
        "Runtime Secret 이름 BLOGGER_TOKEN_JSON 으로 token.json 전체 JSON을 등록하세요."
    )


if __name__ == "__main__":
    main()
