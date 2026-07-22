# blogger

트렌드 키워드 기반 Blogger 정보성 포스팅용 저장소입니다.

## 로컬 설정

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python get_token.py      # OAuth 토큰 1회 발급 → token.json 생성
python publish_test.py   # 테스트 발행
python read_recent_posts.py --limit 6
python format_latest_post_for_slack.py
python publish_trend.py  # 트렌드 수집 → 필터링 → 정보성 글 발행
python backfill_post_images.py  # 이미지 없는 LIVE 글에 헤더 이미지 추가
```

## 자동화 실행 순서 (매 사이클 필수)

Cloud Agent/cron 환경은 매번 새 VM에서 시작될 수 있으므로, 아래 순서를 매 실행마다
빠짐없이 수행해야 합니다 (사람이 직접 실행할 필요는 없음 — `blogger_auth.py`가 1·2번을,
아래 커맨드가 3·4번을 담당):

1. 환경변수 `BLOGGER_CLIENT_SECRET`(또는 `BLOGGER_CLIENT_SECRET_JSON`) 내용을
   `client_secret.json`으로 저장 — `blogger_auth.ensure_client_secret_file()`이
   `load_credentials()` 호출 시 자동 수행
2. 환경변수 `BLOGGER_TOKEN`(또는 `BLOGGER_TOKEN_JSON`) 내용을 `token.json`으로 저장 —
   `blogger_auth.ensure_token_file()`이 `load_credentials()` 호출 시 자동 수행
3. 의존성 설치: `python3 -m pip install -r requirements.txt`
   (또는 `python3 -m pip install google-auth-oauthlib google-auth-httplib2
   google-api-python-client requests Pillow`) — 매번 새 VM일 수 있으므로 매 실행 전 확인
4. 실행: `python3 publish_trend.py`

권장 자동화 Command (한 줄):

```bash
python3 -m pip install -q -r requirements.txt && python3 publish_trend.py
```

시크릿 값(`BLOGGER_CLIENT_SECRET`, `BLOGGER_TOKEN`)은 절대 로그·커밋·채팅 출력에 남기지
않습니다. `client_secret.json`, `token.json`, `.blogger_quota_state.json`은 `.gitignore`에
등록되어 있어 Git에 올라가지 않습니다.

## publish_trend.py

가장 이슈가 큰 정보성 키워드(금융·법률·건강·생활안전·투자 등, 실행당 최대 1개, 기본값)만 골라
"이슈 / 영향 / 확인 방법 / 대응 방법 / 관련 소식" 구조의 글을 작성·발행합니다.

- `trend_sources.py`: Google Trends KR RSS, loword.co.kr 실시간 검색어(헤드리스 크롬 렌더링),
  blackkiwi.net 트렌드 JSON API(`/api/service/keyword/issue-keywords`, `new-keywords`)에서
  1h/4h/24h 창으로 키워드를 수집하고, Google News RSS로 각 키워드의 실제 보도를 가져옵니다.
- `keyword_filter.py`: 연예·스포츠·단순 인명 이슈를 제외하고, 실제 보도 내용을 근거로
  금융/투자/건강/생활안전/법률 카테고리 여부와 "한 사건에 대한 보도인지(헤드라인 응집도)"를 판단합니다.
- `content_writer.py`: 실제 뉴스 헤드라인을 근거로 5단 구조의 본문과 제목을 생성합니다.
- `post_images.py`: **한국 뉴스 썸네일형(16:9)** 이미지를 생성합니다.
  - 하단 1/3 어두운 반투명 배너 + 흰색 메인(~8자) + 노랑/시안 서브(~14자)
  - 우측 하단 `@욘두두` 워터마크 필수(없으면 발행 거부)
  - JPG 1280px로 `posts/images/thumb-{slug}.jpg` 저장 → git commit/push
  - 공개 URL: `https://cdn.jsdelivr.net/gh/yeonjoo2025/blogger@{sha}/posts/images/thumb-{slug}.jpg`
  - 본문 최상단에 `<p><img class="post-thumb" ...></p>` 삽입
  - `publish_trend.py`가 매 발행 직전 자동 호출. 재적용: `python3 backfill_post_images.py --replace`
- `backfill_post_images.py`: 이미지 없는 LIVE 글 추가, 또는 `--replace`로 기존 썸네일 재생성.
- `publish_trend.py`: 위 과정을 조율하고 Blogger에 발행합니다. 신규 발행 한도가 막히면
  (또는 403/429) 그날은 더 이상 글을 생성·수정하지 않고 종료합니다. 애매한 키워드는 억지로 쓰지 않고 건너뜁니다.

### 발행 개수 조절 (편집 정책 vs API 할당량)

두 개의 서로 다른 개념을 분리해서 관리합니다.

- **`BLOGGER_MAX_POSTS_PER_RUN` (기본값 1)**: 한 번 실행할 때 작성할 주제 개수(편집 정책).
  이 자동화는 4시간마다(하루 6회) 실행되므로 기본값 1이면 하루 최대 6개 글을 쓰게 되어,
  "가장 이슈가 되는 것만, 애매하면 줄인다"는 원칙과 잘 맞습니다. API 할당량과는 무관하게
  콘텐츠 품질 기준으로 정하는 값입니다.
- **`BLOGGER_MAX_NEW_POSTS_PER_DAY` (기본값 50)**: Blogger API의 "신규 글 발행"(`posts.insert()`)에
  대해 통상적으로 알려진(공식 문서화는 아니지만 다년간 다수 개발자가 공통적으로 보고한) 하루
  상한 추정치입니다. 다만 신생 블로그·신생 앱은 이보다 훨씬 낮은 한도(예: 6개)에서 막히는
  경우가 흔합니다. 실제로 403/429를 받거나 오늘 발행 수가 한도에 도달하면(`api_blocked`),
  **그날은 `posts.insert()` 호출을 완전히 중단**하고 다음 주기로 넘깁니다 — 대신 완성된 글은
  버리지 않고 `pending_posts/`에 저장해 수동 게시로 넘깁니다. 한도 소진 여부는
  `.blogger_quota_state.json`(Git에 커밋하지 않음)에 KST 날짜 기준으로 기록되어, 같은 날
  재실행 시 불필요한 재시도를 막아 줍니다.
  - 단, **아래 "빈 글 인계" 경로(`posts.patch()`)는 이 quota 상태와 무관하게 항상 먼저
    시도됩니다.** 이 계정은 신규 글 생성 자체가 계정 단위로 차단되어 있어 `posts.insert()`가
    거의 항상 403이 나므로, 사람이 만들어 둔 빈 LIVE 글을 채우는 patch 경로가 실질적인 주
    발행 수단입니다. 이 경로를 quota로 막으면 이 블로그는 사실상 아무것도 발행할 수 없게
    되므로 의도적으로 별도 취급합니다.

Cloud Agent 자동화에서는 `BLOGGER_CLIENT_SECRET` / `BLOGGER_TOKEN` 환경변수(시크릿)로부터
`client_secret.json` / `token.json`을 만든 뒤 실행합니다.

`client_secret.json`, `token.json`, `.blogger_quota_state.json`은 Git에 올리지 마세요.

### 빈 글 인계 - API 차단 시 1차 우회 경로 (권장)

이 계정은 `posts.insert()`(새 글 생성)가 차단되어 있지만, **이미 존재하는 글의
제목/본문을 수정하는 `posts.patch()`는 정상 동작**합니다. 그래서 Blogger 웹 UI에서
사람이 직접 **빈 LIVE 글**을 몇 개 "게시"해 두면, 자동화가 그 글을 찾아 실제
콘텐츠로 덮어씁니다.

**사용법 (가장 확실한 방법)**:
1. Blogger 웹 UI → "새 게시물"
2. 제목은 `빈 포스터` / `빈석` 등 아무거나, 본문은 비워 두거나 한 줄만
3. **"게시"** 를 눌러 LIVE로 올립니다 (초안이 아니라 게시)
4. 다음 자동화 실행이 본문이 비어 있는 LIVE 글을 찾아 `posts.patch()`로
   제목·본문을 실제 콘텐츠로 교체합니다

초안(Draft)으로만 저장해도 시도는 하지만, LIVE 빈 글 방식이 실제로 확인된
우회 경로입니다. 둘 다 실패하면 아래 `pending_posts/` 방식으로 전환됩니다.

### 수동 게시 대체 경로 (`pending_posts/`)

Blogger 계정이 "원치 않는 콘텐츠 전송" 등의 이유로 API 쓰기(`posts.insert`/`posts.update`/
`posts.publish` 전부)가 차단되면(403이 계속 발생), 신규 발행/기존 글 수정은 전혀 시도하지
않지만 그렇다고 이미 모든 검증을 통과한 주제의 콘텐츠를 버리지는 않습니다. 대신 제목+본문을
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
