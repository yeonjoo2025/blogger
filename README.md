# blogger

트렌드·슬랙 키워드 기반 Blogger 자동 포스팅 저장소입니다.  
게이트·썸네일·쿼터는 유지하고, **상업 검색 의도 · 성과 피드백 · 내부링크 · 라벨 품질**로 SEO/수익을 쌓도록 설계되어 있습니다.

## 로컬 설정

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client requests Pillow
python get_token.py      # OAuth 토큰 1회 발급 → token.json 생성
python publish_test.py   # 테스트 발행
python read_recent_posts.py --limit 6
python fetch_stats.py    # 조회수·카테고리·intent·갱신 후보
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

## 자동화 Instructions

- 트렌드: `automation-prompt-trend-to-blogger.md`
- 슬랙: `automation-prompt-slack-to-blogger.md`  
  → 둘 다 `publish_trend.py` 품질 게이트를 통과해야 발행됩니다.

## 발행 한 줄

```bash
# pending_posts/{slug}.md 에 title/labels/keyword/intent 작성 후
python3 fetch_stats.py
python3 publish_trend.py --slug {slug} --keyword "{키워드}" --refresh-stats
# exit 2 → AI 썸네일 저장 후 동일 명령 재실행
```

## 품질·쿼터 기본값

| 항목 | 기본 |
|------|------|
| 본문 | ≥2500자, FAQ≥3, 공식 URL≥1, 내부링크≥2 |
| 라벨 | 허용 8개만(생활정보·세금·금융·예약·캠핑·IT·혜택·사이트안내), 글당 2~3 |
| 일일 발행 | 0 (AdSense 복구; 해제 후 env로 상향) |
| 간격 | 240분 |
| 카테고리 캡 | 전부 0 |

### 선택 환경변수

- `BLOGGER_MIN_INTENT_SCORE` / `BLOGGER_MIN_INTENT_SCORE_FINANCE`
- `BLOGGER_MIN_SELECTION_SCORE`
- `BLOGGER_REQUIRE_INTERNAL_LINKS` (`0`이면 내부링크 검사 생략)
- `BLOGGER_DAILY_CAP_FINANCE` 등
- `BLOGGER_REQUIRE_AI_THUMB` / `BLOGGER_ALLOW_PILLOW_THUMB`(켜지 말 것)

### 성과 피드백 (선택)

GSC 등에서 URL별 클릭을 넣을 수 있습니다.

```json
{
  "urls": {
    "https://yeondodo.blogspot.com/...": { "clicks": 120, "impressions": 3000 }
  }
}
```

파일명: `.blogger_performance.json` (Git 제외). `fetch_stats.py`가 refresh 후보·선정 힌트에 반영합니다.
