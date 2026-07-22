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

가장 이슈가 큰 정보성 키워드(금융·법률·건강·생활안전·투자 등, 실행당 최대 1개, 기본값)만 골라
"이슈 / 영향 / 확인 방법 / 대응 방법 / 관련 소식" 구조의 글을 작성·발행합니다.

- `trend_sources.py`: Google Trends KR RSS, loword.co.kr 실시간 검색어(헤드리스 크롬 렌더링),
  blackkiwi.net 트렌드 JSON API(`/api/service/keyword/issue-keywords`, `new-keywords`)에서
  1h/4h/24h 창으로 키워드를 수집하고, Google News RSS로 각 키워드의 실제 보도를 가져옵니다.
- `keyword_filter.py`: 연예·스포츠·단순 인명 이슈를 제외하고, 실제 보도 내용을 근거로
  금융/투자/건강/생활안전/법률 카테고리 여부와 "한 사건에 대한 보도인지(헤드라인 응집도)"를 판단합니다.
- `content_writer.py`: 실제 뉴스 헤드라인을 근거로 5단 구조의 본문과 제목을 생성합니다.
- `publish_trend.py`: 위 과정을 조율하고 Blogger에 발행합니다. 신규 발행 한도가 막히면
  (또는 403/429) 그날은 더 이상 글을 생성·수정하지 않고 종료합니다. 애매한 키워드는 억지로 쓰지 않고 건너뜁니다.

### 발행 개수 조절 (편집 정책 vs API 할당량)

두 개의 서로 다른 개념을 분리해서 관리합니다.

- **`BLOGGER_MAX_POSTS_PER_RUN` (기본값 1)**: 한 번 실행할 때 작성할 주제 개수(편집 정책).
  이 자동화는 4시간마다(하루 6회) 실행되므로 기본값 1이면 하루 최대 6개 글을 쓰게 되어,
  "가장 이슈가 되는 것만, 애매하면 줄인다"는 원칙과 잘 맞습니다. API 할당량과는 무관하게
  콘텐츠 품질 기준으로 정하는 값입니다.
- **`BLOGGER_MAX_NEW_POSTS_PER_DAY` (기본값 50)**: Blogger API의 "신규 글 발행"에 대해
  통상적으로 알려진(공식 문서화는 아니지만 다년간 다수 개발자가 공통적으로 보고한) 하루 상한
  추정치입니다. 다만 신생 블로그·신생 앱은 이보다 훨씬 낮은 한도(예: 6개)에서 막히는 경우가
  흔합니다. 이 값은 상한선 추정치로만 쓰이고, 실제로 403/429를 받거나 오늘 발행 수가 한도에
  도달하면 **그날은 신규 생성·기존 글 업데이트를 모두 중단**하고 다음 주기로 넘깁니다. 한도
  소진 여부는 `.blogger_quota_state.json`(Git에 커밋하지 않음)에 KST 날짜 기준으로 기록되어,
  같은 날 재실행 시 불필요한 재시도를 막아 줍니다.

Cloud Agent 자동화에서는 `BLOGGER_CLIENT_SECRET` / `BLOGGER_TOKEN` 환경변수(시크릿)로부터
`client_secret.json` / `token.json`을 만든 뒤 실행합니다.

`client_secret.json`, `token.json`, `.blogger_quota_state.json`은 Git에 올리지 마세요.

### 수동 게시 대체 경로 (`pending_posts/`)

Blogger 계정이 "원치 않는 콘텐츠 전송" 등의 이유로 API 쓰기(`posts.insert`)가
차단되면(403이 계속 발생), 신규 발행/기존 글 수정은 전혀 시도하지 않지만 그렇다고
이미 모든 검증을 통과한 주제의 콘텐츠를 버리지는 않습니다. 대신 제목+본문을
`pending_posts/타임스탬프_키워드.html` 파일로 저장합니다.

- 이 폴더는 Git에 커밋됩니다 - 리포지토리/PR에서 바로 확인할 수 있습니다.
- 파일을 열어 제목과 본문을 그대로 Blogger 웹 UI에 복사해 수동으로 게시하면 됩니다.
- 다음 실행 시 해당 키워드가 실제 라이브 글로 확인되면 그 pending 파일은 자동으로
  삭제됩니다(수동 게시 여부를 읽기 전용 `posts.list` API로 계속 확인하기 때문에,
  쓰기 API가 막혀 있어도 이 감지는 정상 동작합니다).
- API 쓰기가 다시 정상화되면 별도 설정 변경 없이 자동으로 API 발행으로 복귀합니다.

## Cloud Agent 시크릿 (필수)

자동화/Cloud Agent는 저장소에 `token.json`이 없습니다. 아래를 등록하세요.

1. [Cloud Agents 대시보드](https://www.cursor.com/dashboard/cloud-agents) → **Secrets**
2. 가능하면 **Personal** 스코프로 등록 (Environment 스코프는 주입이 안 되는 경우가 있음)
3. Runtime Secret 추가:

| Name | Value |
|------|--------|
| `BLOGGER_TOKEN` | 로컬 `token.json` **전체 JSON 내용** |

선택:

| Name | Value |
|------|--------|
| `BLOGGER_CLIENT_SECRET` | `client_secret.json` 전체 JSON |

스크립트는 `token.json`이 없으면 `BLOGGER_TOKEN`(또는 `BLOGGER_TOKEN_JSON`)에서 파일을 만듭니다.

시크릿 등록 후 자동화를 **새로 Run** 하세요 (이미 떠 있던 run에는 시크릿이 안 들어갈 수 있습니다).
