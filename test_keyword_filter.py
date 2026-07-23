"""Unit checks for stronger near-duplicate matching."""

from __future__ import annotations

import unittest

from keyword_filter import is_near_duplicate


class NearDuplicateTests(unittest.TestCase):
    def test_google_earnings_title_variants_match(self) -> None:
        self.assertTrue(
            is_near_duplicate(
                "구글 실적발표",
                "구글(알파벳) Q2 실적 전, CapEx·클라우드·AI를 보는 법",
            )
        )
        self.assertTrue(
            is_near_duplicate(
                "구글 실적발표",
                "구글 실적발표, 실적 숫자·관전 포인트와 대응 체크리스트",
            )
        )
        self.assertTrue(
            is_near_duplicate(
                "알파벳 어닝스",
                "구글(알파벳) Q2 실적 전, CapEx·클라우드·AI를 보는 법",
            )
        )

    def test_same_entity_different_topic_does_not_match(self) -> None:
        self.assertFalse(
            is_near_duplicate(
                "구글 실적발표",
                "구글, 제미나이 3.6 플래시 등 경량 AI 모델 3종 출시…프로는 또 연기",
            )
        )

    def test_same_topic_different_entity_does_not_match(self) -> None:
        self.assertFalse(
            is_near_duplicate(
                "구글 실적발표",
                "마이크론(MU) 실적·UBS 목표가, 숫자로 보는 AI 메모리 붐",
            )
        )
        self.assertFalse(
            is_near_duplicate(
                "외국인 6일 순매수",
                "구글(알파벳) Q2 실적 전, CapEx·클라우드·AI를 보는 법",
            )
        )

    def test_tesla_earnings_token_coverage(self) -> None:
        self.assertTrue(
            is_near_duplicate(
                "테슬라 실적",
                "테슬라 Q2 인도 약 48만 대, 7월 22일 실적에서 볼 것",
            )
        )


if __name__ == "__main__":
    unittest.main()
