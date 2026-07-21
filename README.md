# blogger

트렌드 키워드 기반 Blogger 정보성 포스팅용 저장소입니다.

## 로컬 설정

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client requests
python get_token.py      # OAuth 토큰 1회 발급 → token.json 생성
python publish_test.py   # 테스트 발행
python read_recent_posts.py --limit 6
python format_latest_post_for_slack.py
python publish_trend.py  # 트렌드 수집 → 필터링 → 정보성 글 발행
```

## publish_trend.py

가장 이슈가 큰 정보성 키워드(금융·법률·건강·생활안전·투자 등, 최대 1~3개)만 골라
"이슈 / 영향 / 확인 방법 / 대응 방법 / 관련 소식" 구조의 글을 작성·발행합니다.

- `trend_sources.py`: Google Trends KR RSS, loword.co.kr 실시간 검색어(헤드리스 크롬 렌더링),
  blackkiwi.net 트렌드(best-effort)에서 1h/4h/24h 창으로 키워드를 수집하고,
  Google News RSS로 각 키워드의 실제 보도를 가져옵니다.
- `keyword_filter.py`: 연예·스포츠·단순 인명 이슈를 제외하고, 실제 보도 내용을 근거로
  금융/투자/건강/생활안전/법률 카테고리 여부와 "한 사건에 대한 보도인지(헤드라인 응집도)"를 판단합니다.
- `content_writer.py`: 실제 뉴스 헤드라인을 근거로 5단 구조의 본문과 제목을 생성합니다.
- `publish_trend.py`: 위 과정을 조율하고 Blogger에 발행합니다. 신규 발행이 403/429로 막히면
  가장 오래된 기존 글을 같은 규칙의 글로 업데이트합니다. 애매한 키워드는 억지로 쓰지 않고 건너뜁니다.

Cloud Agent 자동화에서는 `BLOGGER_CLIENT_SECRET` / `BLOGGER_TOKEN` 환경변수(시크릿)로부터
`client_secret.json` / `token.json`을 만든 뒤 실행합니다.

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
