# blogger

트렌드 키워드 기반 Blogger 자동 포스팅용 저장소입니다.

## 로컬 설정

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
python get_token.py      # OAuth 토큰 1회 발급 → token.json 생성
python publish_test.py   # 테스트 발행
python read_recent_posts.py --limit 6
python format_latest_post_for_slack.py
```

`client_secret.json`, `token.json`은 Git에 올리지 마세요.

## Cloud Agent 시크릿 (필수)

자동화/Cloud Agent는 저장소에 `token.json`이 없습니다. 아래를 등록하세요.

1. [Cloud Agents 대시보드](https://www.cursor.com/dashboard/cloud-agents) → **Secrets**
2. 가능하면 **Personal** 스코프로 등록 (Environment 스코프는 주입이 안 되는 경우가 있음)
3. Runtime Secret 추가:

| Name | Value |
|------|--------|
| `BLOGGER_TOKEN_JSON` | 로컬 `token.json` **전체 JSON 내용** |

선택:

| Name | Value |
|------|--------|
| `BLOGGER_CLIENT_SECRET_JSON` | `client_secret.json` 전체 JSON |

스크립트는 `token.json`이 없으면 `BLOGGER_TOKEN_JSON`에서 파일을 만듭니다.

시크릿 등록 후 자동화를 **새로 Run** 하세요 (이미 떠 있던 run에는 시크릿이 안 들어갈 수 있습니다).
