# blogger

검색 트렌드 키워드를 모아 **돈이 되거나 궁금한 주제의 정보성 가이드 글**을 Blogger에 발행하는 저장소입니다.

## 키워드 수집 소스

- [Google Trends KR](https://trends.google.co.kr/trending?geo=KR)
- [BlackKiwi 트렌드](https://blackkiwi.net/service/trend)
- [Loword 키워드 트렌드](https://loword.co.kr/keywordTrend)

## 시간 구간

| 구간 | 수집 방식 |
| --- | --- |
| 1시간 | Loword 시간대 검색어 + Google 최근(4h) 보조 |
| 4시간 | Google Trends `hours=4` + Loword 최근 4시간 |
| 24시간 | Google Trends `hours=24` + BlackKiwi 이슈/신규 + Loword 샘플 |

## 발행 규칙

- 엔터테인먼트·게임성 키워드 제외
- 금융·법률·건강·자격·생활안전 등 **정보성/실용** 키워드 우선
- 글 1개 = 키워드 1개
- 제목은 `방법` / `상세 안내` / `총정리` 형식
- 본문은 개념 → 확인 방법 → 체크리스트 → 관련 소식 구조

## 로컬 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
python get_token.py
python fetch_trends.py    # 수집/선정 미리보기
python publish_trend.py   # 가이드 글 발행
```

## Cloud Agent / 자동화

1. `BLOGGER_CLIENT_SECRET` → `client_secret.json`
2. `BLOGGER_TOKEN` → `token.json`
3. `python3 -m pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client`
4. `python3 publish_trend.py`

`client_secret.json`, `token.json`은 Git에 올리지 마세요.
