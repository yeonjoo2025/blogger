# blogger

트렌드 키워드 기반 Blogger 자동 포스팅용 저장소입니다.

## 로컬 설정

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
python get_token.py      # OAuth 토큰 1회 발급
python publish_test.py   # 테스트 발행
```

`client_secret.json`, `token.json`은 Git에 올리지 마세요. Cursor Cloud Agent Secrets로 등록합니다.
