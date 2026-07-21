# 오토메이션 프롬프트 (복사해서 Cursor Automation에 붙여넣기)

아래 내용을 오토메이션 프롬프트로 사용하세요.  
오토메이션: https://cursor.com/automations/3dedad6e-84c4-11f1-a7d1-d6b4613131ce

```text
시작 시 반드시:
1) 환경 변수 BLOGGER_CLIENT_SECRET 내용을 client_secret.json 파일로 저장
2) 환경 변수 BLOGGER_TOKEN 내용을 token.json 파일로 저장
3) python3 -m pip로 google-auth-oauthlib google-auth-httplib2 google-api-python-client 설치
4) python3 publish_trend.py 실행

목표:
가장 이슈가 큰 정보성 키워드만 골라, 독자가 “무슨 일인지 / 영향 / 방법 / 해결”을 바로 이해하게 글을 작성·발행한다.

키워드 수집 소스:
- https://trends.google.co.kr/trending?geo=KR
- https://blackkiwi.net/service/trend
- https://loword.co.kr/keywordTrend

시간 구간:
- 1시간, 4시간, 24시간 기준으로 수집·비교

선정 규칙:
- 엔터테인먼트·연예·단순 인명·스포츠 경기 결과 제외
- 돈이 되거나 실생활에 영향 있는 이슈만 선정 (금융·법률·건강·생활안전·투자 등)
- 가장 이슈가 되는 것만 작성. 최대 1~3개
- 애매하면 억지로 쓰지 말고 줄인다

글 작성 규칙:
- 글 1개 = 키워드/이슈 1개
- 제목만 읽어도 이슈와 유용성이 보이게 작성 (방법·영향·대응이 드러날 것)
- 본문 필수 구조:
  1) 이슈가 무엇인가
  2) 무엇이 영향받는가
  3) 관련해서 확인할 방법
  4) 해결·대응 방법
  5) 관련 소식(있으면)
- 추상적 문구(“관심이 많습니다”)만 반복하지 말 것
- 본문에 ‘자동 포스팅’ 표현 금지

발행/운영:
- 기본 명령: python3 publish_trend.py
- Blogger 신규 발행이 막히면(403/429) 오래된 글을 같은 규칙의 정보성 글로 업데이트
- 시크릿/토큰 값은 로그·커밋·채팅에 출력하지 말 것
- client_secret.json, token.json 은 Git에 올리지 말 것
```
