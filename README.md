# blogger

검색 트렌드에서 **가장 이슈가 큰 정보성 주제 1~3개만** 골라 Blogger에 발행합니다.

## 글 작성 기준

각 글은 아래 구조를 따릅니다.

1. 이슈가 무엇인가  
2. 무엇이 영향받는가  
3. 관련해서 확인할 방법  
4. 해결·대응 방법  
5. 관련 소식

제목만 읽어도 이슈와 대응 포인트가 보여야 합니다.

## 키워드 소스

- [Google Trends KR](https://trends.google.co.kr/trending?geo=KR)
- [BlackKiwi 트렌드](https://blackkiwi.net/service/trend)
- [Loword 키워드 트렌드](https://loword.co.kr/keywordTrend)

시간 구간: 1시간 / 4시간 / 24시간

## 실행

```bash
python3 -m pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
# BLOGGER_CLIENT_SECRET -> client_secret.json
# BLOGGER_TOKEN -> token.json
python3 publish_trend.py
```

## 오토메이션 프롬프트

Cursor Automation에 넣을 최신 프롬프트는 [`AUTOMATION_PROMPT.md`](./AUTOMATION_PROMPT.md)를 사용하세요.
