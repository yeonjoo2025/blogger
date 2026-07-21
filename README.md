# blogger

트렌드 키워드 기반 Blogger 자동 포스팅용 저장소입니다.

## 로컬 설정

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
python get_token.py       # OAuth 토큰 1회 발급
python publish_test.py    # 테스트 발행
python publish_trend.py   # 트렌드 본글 발행
```

## Cloud Agent / 자동화

시작 시 시크릿을 파일로 내려받은 뒤 발행합니다.

1. `BLOGGER_CLIENT_SECRET` → `client_secret.json`
2. `BLOGGER_TOKEN` → `token.json`
3. `python3 -m pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client`
4. `python3 publish_trend.py`

`client_secret.json`, `token.json`은 Git에 올리지 마세요. Cursor Cloud Agent Secrets로 등록합니다.
