# blogger

트렌드 키워드 기반 Blogger 자동 포스팅 스크립트 모음입니다. Google Blogger API v3를 사용합니다.

## Cursor Cloud specific instructions

### 서비스 개요

이 저장소는 GUI가 없는 Python 스크립트 모음입니다. 모두 `blogger_auth.py`의 `load_credentials()`를 통해 실제 Blogger API에 인증합니다.

- `read_recent_posts.py --limit N` — 최근 글 읽기 (읽기 전용)
- `format_latest_post_for_slack.py` — 최신 글을 Slack용 텍스트로 변환 (읽기 전용)
- `publish_test.py` — 테스트 글 발행 (쓰기)
- `get_token.py` — 로컬 OAuth 토큰 발급 (Cloud에서는 불필요)

표준 실행 방법은 `README.md`를 참고하세요. 아래는 Cloud 환경에서만 유효한 비자명한 주의사항입니다.

### 가상환경

- 의존성은 `.venv/`에 설치됩니다. 스크립트 실행 전 `source .venv/bin/activate` 하거나 `.venv/bin/python`을 직접 사용하세요.
- 시스템 Python은 externally-managed(Debian)라 전역 `pip install`이 막혀 있습니다. 반드시 venv를 사용하세요.

### 시크릿 이름 불일치 (중요)

`blogger_auth.py`는 환경변수 `BLOGGER_TOKEN_JSON`/`TOKEN_JSON`과 `BLOGGER_CLIENT_SECRET_JSON`/`CLIENT_SECRET_JSON`을 찾지만, 실제 등록된 Cloud 시크릿 이름은 **`BLOGGER_TOKEN`**, **`BLOGGER_CLIENT_SECRET`** 입니다. 이름이 달라 코드가 자동으로 파일을 만들지 못합니다.

따라서 스크립트를 돌리기 전에 env 시크릿으로 자격증명 파일을 만들어야 합니다 (둘 다 `.gitignore` 대상, 커밋되지 않음):

```bash
printf '%s' "$BLOGGER_TOKEN" > token.json
printf '%s' "$BLOGGER_CLIENT_SECRET" > client_secret.json
```

`token.json`이 존재하면 `load_credentials()`가 이를 우선 사용하고 만료 시 refresh_token으로 자동 갱신합니다.

### 쓰기 권한 제약 (확인됨)

현재 제공된 토큰으로 **읽기(list/get)는 정상 동작**하지만, `posts.insert`(발행/초안 모두)는 `403 The caller does not have permission`을 반환합니다. 인증(scope는 full `blogger`)이 아니라 해당 블로그에 대한 계정의 작성자/관리자 권한 문제입니다. `publish_test.py`가 실패하면 이는 환경 설정 문제가 아니라 토큰 계정 권한 문제이며, 쓰기 권한이 있는 계정의 토큰을 `BLOGGER_TOKEN`으로 다시 등록해야 합니다.
