# blogger

Google Trends(한국) 검색량 기준 정보성 글을 Blogger에 발행하는 저장소입니다.

## 발행 규칙

- 주기: 4시간마다
- 데이터: [Google Trends KR · 지난 4시간 · 검색량순](https://trends.google.com/trending?geo=KR&hours=4&sort=search-volume)
- 방식: **카테고리별 검색량 TOP 5** 키워드를 골라 상세 정보성 글 작성
- 결과: 카테고리마다 글 1개 (해당 구간 TOP5 해설)

## 로컬 설정

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
python get_token.py       # OAuth 토큰 1회 발급
python fetch_trends.py    # 카테고리별 TOP5 미리보기
python publish_trend.py   # 카테고리별 상세 글 발행
python publish_test.py    # 연결 테스트 발행
```

## Cloud Agent / 자동화

1. `BLOGGER_CLIENT_SECRET` → `client_secret.json`
2. `BLOGGER_TOKEN` → `token.json`
3. `python3 -m pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client`
4. `python3 publish_trend.py`

`client_secret.json`, `token.json`은 Git에 올리지 마세요. Cursor Cloud Agent Secrets로 등록합니다.
