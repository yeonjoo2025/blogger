# blogger

트렌드 키워드 기반 Blogger 자동 포스팅용 저장소입니다.

## Slack 자동화 프롬프트 (필수)

Cursor Automation **Blogger → 네이버용 슬랙 초안** 프롬프트는 아래 파일을 **그대로** 사용합니다.

- [`AUTOMATION_PROMPT.md`](./AUTOMATION_PROMPT.md)
- 대시보드: https://cursor.com/automations/b8250dd3-84e5-11f1-a7d1-d6b4613131ce

핸드폰 Slack → 네이버 붙여넣기 줄바꿈은 **U+2028만** 사용합니다.  
(`format_latest_post_for_slack.for_naver_paste`)

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
