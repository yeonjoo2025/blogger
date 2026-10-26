# 트렌드 → Blogger 자동 포스팅 Instructions (수익·SEO·AdSense 안전형)

Cursor Automations Instructions에 **아래 “시작 시 반드시”부터 끝까지** 붙여 넣으세요.

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
목표 (고수익 정보 블로그)
════════════════════════════════════════
실시간 이슈 중에서도 **돈이 되거나 실생활에 바로 쓰는 검색 의도**만 골라,
독자가 “신청/예약/비교/예매”를 끝낼 수 있는 글을 작성·발행한다.

우선순위:
1) 상업·행동 의도 (신청·예약·예매·가격·비교·혜택·지원금·환급)
2) 기존 성과 패턴·갱신(refresh) 후보
3) 가이드·IT > 사회제도 ≫ 금융 헤드라인
4) 스포츠/연예/단순 뉴스 요약 = 발행 금지

게이트·썸네일·쿼터·라벨 sanitize·제목 공장 금지는 **코드가 최종 심판**. 우회 금지.

════════════════════════════════════════
AdSense 재발 방지 — 발행 전 필수 게이트 (최우선)
════════════════════════════════════════
이 블록에 하나라도 걸리면 SKIP 하고 발행하지 않는다. 우회 금지.

[G0] 복구 모드 (애드센스 “최소 콘텐츠/저가치/웹마스터 품질” 경고 해소 전)
- 실행당 최대 **0개**. 신규 발행 없이 정상 종료.
- refresh·트렌드 포장·공장형 가이드 추가 금지.
- 코드 기본값: 일일 발행 0, 카테고리 캡 전부 0.

[G1] 주제 내구성 테스트 (하나라도 NO면 스킵)
독자가 30일 뒤에도 같은 글로 행동을 끝낼 수 있는가?
- YES 예: 신청/예약/요금/자격/가입/예매/환급/할인신청/납입
- NO 예: 사고·특보·시위·사이드카·증산·실적속보·한시 메뉴/프로모·연예이슈
NO면 “가이드로 포장”하지 말고 즉시 `SKIP_ONEOFF=`

[G2] 제목 금지·필수 공식
금지:
- `확인 방법…체크리스트` / `확인하는 법…체크리스트` 공장형
- 최근 라이브 글과 뼈대만 같고 키워드만 바꾼 제목
- 낚시·허위 숫자·`뭐길래` 단독

필수 제목 공식 (매 글 A~D 중 하나만, 문형 교체):
- A) `[키워드] [연도/기한] 총정리…[숫자 혜택] [신청|받는]법`
- B) `[키워드], [질문형]? [비교|준비|보는] 법`
- C) `[키워드]이란? [자격·순서] 초보 가이드`
- D) `[키워드] 싸게/쉽게 [행동]…[함정|포인트|기준]`

좋음:
- `ISA 계좌 2026 총정리…납입한도 2000만원·서민형 비과세 신청법`
- `노을캠핑장 예약 경쟁 뚫는 법 2026…인터파크 오픈 타이밍·명당`
나쁨:
- `○○ 확인 방법, … 체크리스트`
- `○○가 뭐길래?` 만

[G3] 본문 최소 증거
- **정보 기준일** 1줄 (YYYY-MM-DD) — 코드가 검사
- 공식/공공 URL ≥1 (실제 href)
- 내부링크 ≥2 (yeondodo.blogspot.com, 자기자신 제외)
- FAQ ≥3 + 체크리스트/피해야 할 실수
- 뉴스 요약만으로 2500자 채우기 금지

[G4] 발행 직전 로그 (없으면 미완료)
```
ADSENSE_GATE=PASS|FAIL
DURABLE=YES|NO
TITLE_PATTERN=A|B|C|D
SKIP_REASON=...
```

이번 실행에서 절대 생략 금지:
A) Blogger labels 12~18개 (`sanitize_labels` 통과, 주제형만 — 방법/확인 등 패딩 금지)
B) AI 시네마틱 썸네일 + jsDelivr CDN (`post-thumb`)
C) 본문 **내부링크 2개 이상** (yeondodo.blogspot.com 기존 글)
D) 공식/신뢰 URL 1개 이상 + FAQ 3개 이상 + 정보 기준일
E) frontmatter `intent:` 필드
F) AdSense 게이트 G0~G4 로그

════════════════════════════════════════
필수 실행 순서 (매 실행 동일)
════════════════════════════════════════
[STEP 1] 자격 증명/의존성 준비 (위 1~3)

[STEP 2] 통계·성과 힌트 갱신
  python3 fetch_stats.py
  - `.blogger_stats.json` 생성/갱신
  - 로그 확인: PAGEVIEWS_* / CATEGORY_COUNTS / INTENT_COUNTS /
    TOP_PATTERNS / PREFER_INTENTS / PREFER_PATTERNS / REFRESH_CANDIDATES
  - `selection_hints.refresh_first` 에 후보가 있으면 **신규 트렌드보다 갱신을 우선**
  - (선택) GSC 클릭 데이터를 `.blogger_performance.json` 에 넣어 두면 URL별 가점에 반영됨

[STEP 3] 키워드 수집·후보 선정
  - 하드필터·카테고리·중복·쿨다운·intent/selection·AdSense 게이트는 코드/본 프롬프트가 최종 심판
  - 에이전트는 후보 확정 후 본문을 `pending_posts/{slug}.md` 로 저장
  - frontmatter 필수: title, labels, keyword, **intent**

[STEP 4] 1차 발행
  python3 publish_trend.py --slug {slug} --keyword "{키워드}" --refresh-stats

[STEP 5] AI 썸네일 (exit code 2 이면 무조건)
  - REQUIRED_IMAGE_PROMPT_BEGIN~END 로 GenerateImage (16:9)
  - REQUIRED_SAVE_PATH 에 저장 후 재실행:
    python3 publish_trend.py --slug {slug} --keyword "{키워드}"

[STEP 6] 성공 검증 (하나라도 실패면 미완료)
  - PUBLISHED_URL=...
  - labels_count 12개 이상(목표 15)
  - class="post-thumb" + jsdelivr.net
  - quality ok / USEFULNESS_SCORE>=7 / INTENT_SCORE 충분
  - SELECTION_SCORE 통과
  - data:image 없음
  - 본문에 내부링크 2+ / 공식 URL / FAQ 3+ / 체크리스트 / 정보 기준일
  - ADSENSE_GATE=PASS, TITLE_PATTERN=A|B|C|D

════════════════════════════════════════
키워드 수집 소스
════════════════════════════════════════
주력:
1) https://blackkiwi.net/service/trend
   (/api/service/keyword/issue-keywords, /api/service/keyword/new-keywords)
2) https://loword.co.kr/keywordTrend

보조(교차검증만):
3) https://trends.google.co.kr/trending?geo=KR
   ※ 구글 트렌드 단독 키워드는 기본 제외

시간: 1h / 4h / 24h 비교. 블랙키위·로워드 순위 기준.

════════════════════════════════════════
선정 우선순위 (수익 의도 먼저)
════════════════════════════════════════
수집 후 아래를 **순서대로** 적용. 상위가 있으면 하위를 보지 않는다.

0순위 (최우선): `fetch_stats` 의 **refresh_first** 후보
   - 기존 가이드/신청/비교 글을 최신 일정·가격·링크로 갱신
   - intent 는 `refresh`, 제목에 연도/월·“최신” 시그널
   - 본문에 이전 글 URL을 내부링크로 포함해도 됨(자기 자신 제외 2개 권장)

1순위: 3사이트 공통 ∩ **강한 상업 의도**
   (신청|예약|예매|가격|비교|혜택|지원금|사전판매|요금|할인|환급|납입)
   ※ `확인`·`체크리스트`만으로는 1순위 불가

2순위: 블랙키위 ∩ 로워드 ∩ 강한 상업 의도

3순위: 한쪽 소스만 + 급상승 + 유익도·intent·내구성(G1) 통과
   - 카테고리 guide/it 우선

4순위(비권장·복구 중 사실상 금지): 금융 실적/티커/주가 헤드라인
   - finance 일일 캡 기본 0
   - 제목에 일정·납입·자격·신청 + 숫자/기한 필수
   - INTENT_SCORE 미달이면 스킵

5순위(금지): 스포츠·연예·news-only · 구글트렌드 단독 · 일회성 사건 포장

같은 티어 안 정렬:
1) SELECTION_SCORE / TOP_PATTERNS 일치
2) intent: apply > how-to|compare|price|refresh > explainer > decision
3) 카테고리 guide/it > society ≫ finance
4) 최근 7일 미작성
→ **1개만** 고른다. 없으면 0개 종료.

════════════════════════════════════════
선정 규칙 — 코드 강제
════════════════════════════════════════
하드 스킵: 엔터/스포츠/일회성·저가치 래퍼 (`blogger_quality.is_hard_skip`)
제목 공장 금지: `확인 방법…체크리스트` (`title_ok` / TITLE_FACTORY_BAD_RE)
실행당 0개 / 일일 기본 **0개** (복구 해제 전까지)
카테고리 캡(기본): sports_ent=0, finance=0, guide=0, it=0, society=0, other=0
intent_score 미달·selection_score 미달이면 0개 종료

로그:
SOURCE_HIT / PICK_TIER / PICK_KEYWORD / PICK_CATEGORY / PICK_INTENT /
SELECTION_SCORE / INTENT_SCORE / USEFULNESS_SCORE / QUOTA_CHECK /
ADSENSE_GATE / DURABLE / TITLE_PATTERN

════════════════════════════════════════
intent 분류 (frontmatter 필수)
════════════════════════════════════════
how-to | compare | price | apply | explainer | decision | refresh

- apply / how-to / compare / price / refresh → 우선 발행
- explainer → 즉시 행동·FAQ·공식링크 강력히 있을 때만
- decision → 금융이면 행동형 제목(일정/납입/자격/신청+숫자) 필수, 아니면 스킵 우선
- news-only → 금지 (생활안전 긴급이어도 일회성이면 기본 스킵)

════════════════════════════════════════
유익도·SEO 게이트 (코드)
════════════════════════════════════════
`blogger_quality.validate_post` / `score_usefulness` 가 검사:
- 본문 ≥2500자
- 한줄요약 / 대상판별 / 즉시행동 / 체크리스트 / FAQ(≥3)
- **정보 기준일** 문구
- **공식 URL ≥1** (go.kr, IR, 회사 뉴스룸 등 — “공식” 단어만으로는 불가)
- **내부링크 ≥2** (yeondodo.blogspot.com)
- 라벨 12~18 (주제형만, 방법/확인/FAQ 등 제네릭 패딩 거부)
- 제목 상업·행동 시그널 + 공장형 제목 거부
- 표(일정·가격·비교) 권장

작성 전 내부 확정:
1. 독자 한 줄 목표
2. 즉시 행동 1개
3. 공식 확인 링크 1개
4. FAQ 3개
5. 피해야 할 실수 1개
6. 내부링크에 넣을 기존 글 2개
7. intent + category + TITLE_PATTERN(A~D)
8. DURABLE=YES

════════════════════════════════════════
글 작성 규칙
════════════════════════════════════════
제목: A~D 공식 중 하나 (위 AdSense 게이트)
  좋음: `ISA 계좌 2026 총정리…납입한도 2000만원·서민형 비과세 신청법`
  나쁨: `○○ 확인 방법, … 체크리스트` / `○○가 뭐길래?` 만

권장 본문 구조 (기능 충족, 문구 복붙 금지):
1) **정보 기준일** (맨 위 또는 썸네일 직후)
2) 한 줄 요약 (검색 질문에 대한 직접 답)
3) 핵심 사실 표 (날짜·숫자·대상·가격)
4) 나에게 해당되는지
5) 지금 할 방법 / 단계 (공식 링크)
6) 체크리스트 / 피해야 할 실수
7) FAQ 3~5 (실제 검색 질문형)
8) **관련 글** — 내부링크 2~3개 (제목+URL)
9) 관련 소식 + 한눈에 정리 + 정보성 주의 1줄

금지: 추상 상투구, ‘자동 포스팅’, 투자 매수매도 지시, 길이 채우기용 군더더기,
     일회성 뉴스를 가이드처럼 포장

pending_posts/{slug}.md:
```md
---
title: {A~D 공식 제목}
labels: [주제형 태그 12~15개]
keyword: {원본 키워드}
intent: apply
---

(본문 — 첫 줄 근처에 정보 기준일: YYYY-MM-DD)
```

════════════════════════════════════════
태그 / 썸네일 / 발행
════════════════════════════════════════
태그: sanitize 통과본, 목표 15, 최소 12, 최대 18
썸네일: AI plate 필수, Pillow/data URI 금지, @욘두두 워터마크
  가능하면 이미지 헤드라인에 숫자·일정 포함 (CTR)

명령:
  python3 fetch_stats.py
  python3 publish_trend.py --slug {slug} --keyword "{키워드}"

저장소: yeonjoo2025/blogger / main
블로그 ID: 4736025457821775813

코드 우회 금지:
- fetch_stats.py / blogger_quality.py / blogger_quota.py
- publish_from_posts.py / publish_trend.py

발행 우선순위: 빈 셸 patch → 없을 때만 insert → 403/429면 종료

환경변수(선택):
- BLOGGER_MAX_NEW_POSTS_PER_DAY (기본 0, 복구 해제 후에만 상향)
- BLOGGER_MIN_INTERVAL_MINUTES (240)
- BLOGGER_DAILY_CAP_FINANCE (0) / _GUIDE (0) / _IT (0) / _SOCIETY (0)
- BLOGGER_MIN_INTENT_SCORE (4) / _FINANCE (5)
- BLOGGER_MIN_SELECTION_SCORE (6)
- BLOGGER_REQUIRE_INTERNAL_LINKS (1)
- BLOGGER_REQUIRE_AI_THUMB (1)
- BLOGGER_ALLOW_PILLOW_THUMB (켜지 말 것)

Git: 시크릿·token·.blogger_*·pending_posts·generated_images 커밋 금지
커밋 허용: posts/images/thumb-*.jpg, posts/*.md

════════════════════════════════════════
완료 기준
════════════════════════════════════════
선정 주제가 있으면:
1) ADSENSE_GATE=PASS, DURABLE=YES, TITLE_PATTERN 기록
2) USEFULNESS_SCORE>=7, INTENT/SELECTION 통과
3) PUBLISHED_URL, labels 12+, post-thumb CDN
4) 내부링크·공식URL·FAQ·체크리스트·정보 기준일 실재
미달이면 SKIP_* 로그만 남기고 발행하지 않음 (정상 종료)
태그/썸네일/내부링크 없이 본문만 올리면 미완료
