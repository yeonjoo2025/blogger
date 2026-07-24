# 트렌드 → Blogger 자동 포스팅 Instructions

Cursor Automations Instructions에 **아래 “시작 시 반드시”부터 끝까지** 붙여 넣으세요.  
(기존 트렌드 자동화 프롬프트를 이 내용으로 교체)

---

시작 시 반드시:
1) 환경 변수 `BLOGGER_CLIENT_SECRET`(또는 `BLOGGER_CLIENT_SECRET_JSON`) 내용을 `client_secret.json` 파일로 저장
2) 환경 변수 `BLOGGER_TOKEN`(또는 `BLOGGER_TOKEN_JSON`) 내용을 `token.json` 파일로 저장
3) `python3 -m pip`로 아래 패키지 설치 (가능하면 `.venv` 사용)
   - google-auth-oauthlib
   - google-auth-httplib2
   - google-api-python-client
   - requests
   - Pillow
4) 아래 “필수 실행 순서”를 한 글자도 빼지 말고 끝까지 수행

════════════════════════════════════════
목표
════════════════════════════════════════
가장 이슈가 큰 **정보성** 키워드만 골라, 독자가 “무슨 일인지 / 영향 / 방법 / 해결”을
바로 이해하게 글을 작성·발행한다. 글은 짧지 않게, 실무에서 바로 써먹을 수 있을
정도로 구체적으로 쓴다.

초기 블로그 통계(조회수·카테고리 믹스)를 반영해,
검색량만 높은 스포츠/연예 요약보다 **가이드·IT·제도 해설**을 우선한다.

이번 자동화에서 자주 빠지는 아래 두 가지를 절대 생략하지 말 것:
A) Blogger labels(태그) 15~20개 (`sanitize_labels` 통과본)
B) 다른 포스트와 같은 품질의 AI 시네마틱 썸네일 + **jsDelivr CDN URL**
   (Pillow 막대그래프/도형 폴백 금지, data URI 썸네일 금지)

════════════════════════════════════════
필수 실행 순서 (매 실행 동일)
════════════════════════════════════════
[STEP 1] 자격 증명/의존성 준비 (위 1~3)

[STEP 2] 통계 갱신 (조회수 피드백)
  python3 fetch_stats.py
  - `.blogger_stats.json` 생성/갱신
  - 로그의 PAGEVIEWS_ALL / CATEGORY_COUNTS 확인
  - 이후 키워드 선정·카테고리 선택에 반영

[STEP 3] 키워드 수집·후보 선정 (아래 소스/티어/필터 규칙)
  - 하드필터·카테고리·중복·쿨다운은 **코드가 최종 심판**
  - 에이전트는 후보를 고른 뒤 본문을 `pending_posts/{slug}.md` 로 저장

[STEP 4] 1차 발행 파이프라인
  python3 publish_trend.py --slug {slug} --keyword "{키워드}" --refresh-stats

[STEP 5] AI 썸네일 필수 처리 (exit code 2 이면 무조건 수행)
  - publish_trend.py 가 AI plate 부재로 exit 2 로 끝나면, 로그에서 다음을 읽는다:
    - REQUIRED_SLUG=...
    - REQUIRED_SAVE_PATH=generated_images/ai-thumb-{slug}.png
    - REQUIRED_IMAGE_PROMPT_BEGIN ~ END 사이 전체 프롬프트
  - 그 프롬프트로 GenerateImage 도구를 즉시 호출한다 (16:9).
  - 결과 이미지를 REQUIRED_SAVE_PATH 경로에 저장한다.
  - 저장 후 반드시 다시 실행:
    python3 publish_trend.py --slug {slug} --keyword "{키워드}"

[STEP 6] 발행 성공 검증 (하나라도 실패면 미완료)
  - PUBLISHED_URL=... 로그
  - labels_count 15개 이상(목표 20)
  - 본문에 class="post-thumb" + jsdelivr.net CDN URL
  - `quality ok` 로그
  - USEFULNESS_SCORE>=7
  - data:image 가 본문에 없을 것

중요:
- AI 썸네일 없이 글을 올리면 실패다. Pillow 폴백·data URI 발행 금지.
- 태그 문장형/잡음 태그는 코드가 제거한다. 통과 후 15개 미만이면 발행 중단.
- “나중에” 하지 말고, 같은 실행 안에서 STEP 2→6을 끝낸다.

════════════════════════════════════════
키워드 수집 소스 (우선순위 중요)
════════════════════════════════════════
주력 소스 (이 둘을 먼저·더 깊게 수집):
1) https://blackkiwi.net/service/trend
   (프론트와 동일한 JSON API 우선:
    /api/service/keyword/issue-keywords,
    /api/service/keyword/new-keywords)
2) https://loword.co.kr/keywordTrend
   (필요 시 헤드리스 렌더링으로 네이버/구글 실시간 검색어 수집)

보조 소스 (교차검증·중복 확인용):
3) https://trends.google.co.kr/trending?geo=KR
   (가능하면 Google Trends KR RSS / 공개 피드 활용)
   ※ 구글 트렌드에만 있는 키워드는 기본 후보에서 제외하거나 최하 우선

시간 구간:
- 1시간, 4시간, 24시간 기준으로 수집·비교
- 블랙키위·로워드를 기준으로 순위를 만들고, 구글 트렌드는 중복 가점에만 사용

════════════════════════════════════════
키워드 선정 우선순위 (필수)
════════════════════════════════════════
수집 후 아래 순서로만 후보를 고른다. 상위 티어가 있으면 하위 티어는 보지 않는다.

1순위 (최우선): **3개 사이트 모두에 등장**하는 키워드
   - 블랙키위 ∩ 로워드 ∩ 구글 트렌드
   - 표기 차이(띄어쓰기·조사·영문/한글)는 정규화 후 매칭
2순위: **블랙키위 ∩ 로워드** 에 공통 등장
3순위: 블랙키위 또는 로워드 중 한쪽에만 있어도,
        순위/급상승이 뚜렷하고 유익도 게이트를 통과하는 경우
4순위(비권장): 구글 트렌드에만 있는 키워드 → 원칙적 스킵
               (생활안전 긴급 + 즉시 행동 체크리스트가 가능할 때만 예외)

같은 티어 안에서는:
1) `fetch_stats.py` 기준 카테고리 가점 (guide/it > society > finance ≫ sports_ent)
2) 급상승/이슈성 점수
3) 유익도 점수
4) 최근 7일 미작성 주제
순으로 1개만 고른다.

════════════════════════════════════════
선정 규칙 (기본 필터) — 코드 강제
════════════════════════════════════════
아래는 프롬프트 권고가 아니라 `blogger_quality.is_hard_skip` / `publish_trend.py` 가 차단한다.

하드 스킵(발행 금지):
- 엔터테인먼트·연예·단순 인명·스포츠 경기결과/개막/캐스팅
- 예: 케스파컵, 오스틴 보스, 메시, KT vs 두산, 어벤져스 개봉 요약 등
- 카테고리 `sports_ent` 는 일일 쿼터 0

우선 후보:
- 돈이 되거나 실생활에 영향 있는 이슈
  (금융·제도·생활안전·IT실무·예약/신청/구매 가이드)

기타:
- 실제 뉴스 보도 또는 공식 문서로 사실관계가 뒷받침되는 것만 선정
- 일반 명사성·응집도 낮은 키워드 제외
- 실행당 기본 1개 (`BLOGGER_MAX_POSTS_PER_RUN=1`)
- 최소 발행 간격 기본 240분 (`BLOGGER_MIN_INTERVAL_MINUTES`)
- 일일 총발행 기본 6개, 카테고리별 캡 적용 (`blogger_quota.py`)
- cron 주기여도 **유익도/쿼터/하드필터 미달이면 0개 종료**
- 로그에 남길 것:
  `SOURCE_HIT=...` / `PICK_TIER=1|2|3` / `PICK_KEYWORD=...` /
  `PICK_CATEGORY=...` / `STATS_CATEGORY_BOOST=...` /
  `USEFULNESS_SCORE=...` / `QUOTA_CHECK=...`

════════════════════════════════════════
유익도 자동화 (필수 — 코드 게이트)
════════════════════════════════════════
목표: “검색량 높은 뉴스 요약”이 아니라 “독자가 바로 써먹는 정보”만 발행.
점수·섹션 검사는 `blogger_quality.score_usefulness` / `validate_post` 가 수행한다.
로그만 남기고 발행하면 실패다.

### A) 의도 분류 (필수)
후보 키워드를 아래 중 하나로 분류한다. 분류 못하면 스킵.
1. `how-to` : 예약/신청/설정/확인 절차가 핵심
2. `explainer` : 용어·제도·구조를 이해해야 다음 행동이 생김
3. `decision` : 일정·숫자·대상·조건을 보고 선택/대응이 필요
4. `news-only` : 사건 전달만 가능 → **원칙적 스킵**
   (예외: 생활안전 긴급 안내이며 즉시 행동 체크리스트가 가능할 때만 허용)

### B) 유익도 점수 (0~10, 7점 미만이면 작성·발행 금지)
|+2| 독자가 **오늘 바로 할 행동** 1개를 구체적으로 적을 수 있음 |
|+2| **공식 출처**(정부·지자체·회사 IR/공시·공식 사이트) 1개 이상 확보 |
|+2| 검색 의도가 “무슨 일?”만이 아니라 **방법/확인/대상/일정** 중 하나를 포함 |
|+1| 숫자·날짜·대상·조건 중 **검증 가능한 팩트 3개 이상** |
|+1| FAQ 포함 |
|+1| 체크리스트 포함 |
|+1| 본문 텍스트 **2500자 이상** |

하드 스킵 (점수와 무관):
- 공식 출처 신호 없음
- 즉시 행동/체크리스트/FAQ/대상판별/한줄요약 섹션 누락
- 본문 2500자 미만
- news-only 이면서 생활안전 긴급이 아님
- 최근 글과 제목 유사(중복) / `뭐길래` 템플릿 과다

### C) 작성 전 출력 체크 (필수)
본문 쓰기 전에 아래를 내부적으로 확정한다. 하나라도 비면 스킵.
1. 독자 한 줄 목표: “이 글을 읽으면 ___를 할 수 있다”
2. 즉시 행동 1개
3. 공식 확인 링크 1개
4. FAQ 후보 3개
5. 피해야 할 실수 1개
6. 카테고리: guide | it | society | finance (sports_ent 금지)

════════════════════════════════════════
글 작성 규칙 (유익도 중심)
════════════════════════════════════════
- 글 1개 = 키워드/이슈 1개
- 제목만 읽어도 **이슈 + 쓸 수 있는 포인트**가 보이게 작성
  (나쁜 예: “○○가 뭐길래?”만
   좋은 예: “○○ 확인하는 법 / 일정·대상·체크리스트”)
- 최근 10개 제목 중 `뭐길래` 는 최대 2개까지만 허용 (코드 검사)
- 본문 최소 2500자(태그만 제거한 텍스트 기준), 짧은 요약체 금지
- 검색 의도 맞추기:
  - 실적발표/어닝스: 대출·세금 프레임 금지.
    “발표 일정 / 실적 숫자·컨센서스 대비 / 관전 포인트 / 어디서 확인” 중심
  - 금융·제도: 일정·적용 대상·내 계약·계좌 확인 중심
  - 생활안전·건강·법률: 영향 대상과 즉시 확인할 행동 중심
  - IT/방법: 단계·화면·주의사항·실패 포인트 중심
- 본문 필수 구조 (기능 충족, 문구 복붙 금지):
  1) 한 줄 요약
  2) 핵심 사실 (날짜·숫자·주체·조건)
  3) 나에게 해당되는지 판별
  4) 지금 확인할 방법 (공식 링크)
  5) 체크리스트 / 피해야 할 실수
  6) FAQ 3~5개
  7) 관련 소식 + 한눈에 정리
- 추상 문구(“관심이 많습니다”, “정보성 이슈로 부각”) 반복 금지
- 본문에 ‘자동 포스팅’ 표현 금지
- 티커/종목코드 사람 읽기 쉬운 표기
  예: tsla → 테슬라(TSLA), 005930 → 삼성전자(005930)

pending 파일 형식 (`pending_posts/{slug}.md`):
```md
---
title: {이슈+행동 포인트가 보이는 제목}
labels: [태그1, 태그2, ...]
keyword: {원본 키워드}
---

(본문 마크다운: 표/목록/제목/링크 사용 가능)
```

════════════════════════════════════════
태그(Blogger labels) — 필수, 15~20개
════════════════════════════════════════
- 직접 대충 넣지 말고, 발행 시 `sanitize_labels()` 통과본을 사용
- 금지: 문장형 태그, `움직였습니다` 같은 본문 조각, 연도만, Corp/Inc, `정보성글` 남발
- 총 글자 수 제한을 넘기면 긴 태그부터 탈락할 수 있음 → 짧고 선명한 토큰 위주
- 목표 20개, 최소 15개 미만이면 발행 중단
- insert / 빈 포스트 patch / draft update 모든 경로에 labels 포함
- 발행 후 labels_count 로그 확인

════════════════════════════════════════
썸네일 — 필수, CDN 고정 파이프라인
════════════════════════════════════════
목표 스타일:
- 시네마틱/포토리얼 뉴스 썸네일
- 배경 장면 안에 한글 헤드라인이 자연스럽게 들어감
- 우측 하단 @욘두두 워터마크
- Pillow 추상 원/막대그래프만 있는 이미지 실패
- data URI 썸네일 실패

파이프라인 (publish_trend.py가 수행):
1) `generated_images/ai-thumb-{slug}.png` 필요 (없으면 exit 2 + REQUIRED_IMAGE_PROMPT)
2) 에이전트 GenerateImage → 저장 → publish_trend.py 재실행
3) `posts/images/thumb-{slug}.jpg` 변환
4) git add/commit/push (썸네일·아카이브 md)
5) 본문 최상단:
   <p><img class="post-thumb" src="https://cdn.jsdelivr.net/gh/yeonjoo2025/blogger@{sha}/posts/images/thumb-{slug}.jpg" ...></p>
6) `BLOGGER_ALLOW_PILLOW_THUMB` 켜서 폴백 발행 금지

GenerateImage 제약:
- 16:9
- 로고/브랜드 마크/실존 연예인 얼굴 금지
- 가짜 확정 숫자 읽히게 넣지 말 것
- 하단 반투명 배너 오버레이 금지

════════════════════════════════════════
발행/운영
════════════════════════════════════════
기본 명령:
  python3 fetch_stats.py
  python3 publish_trend.py --slug {slug} --keyword "{키워드}"

저장소: yeonjoo2025/blogger / 브랜치 main
블로그 ID: 4736025457821775813

관련 코드 (에이전트가 우회하지 말 것):
- `fetch_stats.py` : 조회수·카테고리 통계
- `blogger_quality.py` : 하드필터·라벨·유익도·제목·중복
- `blogger_quota.py` : 쿨다운·일일/카테고리 쿼터
- `publish_from_posts.py` : MD→HTML (표/이미지/헤딩/리스트)
- `publish_trend.py` : 선정 이후 발행 단일 진입점

발행 우선순위:
1) 빈 LIVE/DRAFT 셸이 있으면 patch/update 후 publish
2) 셸이 없을 때만 posts.insert
3) insert 403/429 이고 셸도 없으면 생성/수정 없이 종료

하루·속도 제한(기본값):
- 실행당 1개
- 최소 간격 240분
- 하루 최대 6개
- 카테고리 캡: sports_ent=0, finance=2, guide=3, it=2, society=2
- 상태 파일: `.blogger_quota_state.json`, `.blogger_stats.json`

보안/Git:
- 시크릿/토큰 값을 로그·커밋·채팅에 출력하지 말 것
- client_secret.json, token.json, .blogger_quota_state.json,
  .blogger_stats.json, pending_posts/, generated_images/ 는 Git에 올리지 말 것
- 커밋되는 이미지는 posts/images/thumb-*.jpg (+ 필요 시 posts/*.md) 만

환경변수(선택):
- BLOGGER_MAX_POSTS_PER_RUN (기본 1)
- BLOGGER_MAX_NEW_POSTS_PER_DAY (기본 6)
- BLOGGER_MIN_INTERVAL_MINUTES (기본 240)
- BLOGGER_REQUIRE_AI_THUMB (기본 1)
- BLOGGER_ALLOW_PILLOW_THUMB (기본 미설정, 켜지 말 것)
- BLOGGER_AUTO_GIT_PUSH (기본 1)
- BLOGGER_DAILY_CAP_FINANCE / _GUIDE / _IT / _SOCIETY

════════════════════════════════════════
완료 기준 (전부 만족해야 완료)
════════════════════════════════════════
- fetch_stats.py 실행됨
- publish_trend.py 최종 정상 종료 (AI 썸네일 준비 후 재실행 포함)
- 선정 주제가 있으면:
  1) USEFULNESS_SCORE >= 7
  2) PUBLISHED_URL 확인
  3) labels 15~20개
  4) post-thumb + jsDelivr URL 확인 (data URI 없음)
  5) quality ok
  6) 본문에 즉시행동 + FAQ + 체크리스트 + 공식링크 실재
- 유익도/하드필터/쿼터 미달이면 정상 종료로 간주하고
  `SKIP_LOW_USEFULNESS` / `SKIP_HARD_FILTER` / `SKIP_QUOTA` 로그만 남긴 채 발행하지 않음
- insert 한도 소진이고 빈 포스트도 없으면
  “생성/업데이트 없이 종료” 후 종료
- 애매하면 억지 발행하지 말 것
- 태그/썸네일 없이 “본문만 올림”으로 끝내지 말 것 (미완료)
