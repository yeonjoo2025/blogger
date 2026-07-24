"""Unit checks for Blackkiwi newly-appeared keyword scoring boost."""

from __future__ import annotations

import unittest

from publish_trend import (
    NOVELTY_BASE_BONUS,
    is_blackkiwi_new,
    novelty_bonus,
    score_group,
)
from trend_sources import TrendItem


class NoveltyBonusTests(unittest.TestCase):
    def test_no_bonus_without_blackkiwi_new(self) -> None:
        items = [
            TrendItem(keyword="구글 실적발표", source="blackkiwi_daily", rank=3, windows=("24h",)),
            TrendItem(keyword="구글 실적발표", source="loword_keyword_trend", rank=2, windows=("1h",)),
        ]
        self.assertFalse(is_blackkiwi_new({i.source for i in items}))
        self.assertEqual(novelty_bonus(items), 0.0)

    def test_base_and_rank_bonus_for_new_panel(self) -> None:
        items = [
            TrendItem(keyword="한강밤핑 예약", source="blackkiwi_new", rank=1, windows=("24h",)),
        ]
        bonus = novelty_bonus(items)
        self.assertGreaterEqual(bonus, NOVELTY_BASE_BONUS + 10)
        self.assertTrue(is_blackkiwi_new({i.source for i in items}))

    def test_new_keyword_outranks_stale_riser_on_equal_substance(self) -> None:
        stale = [
            TrendItem(keyword="구글 실적발표", source="blackkiwi_daily", rank=5, windows=("24h",)),
        ]
        fresh = [
            TrendItem(keyword="다자녀가구 통행료 할인 신청", source="blackkiwi_new", rank=2, windows=("24h",)),
            TrendItem(
                keyword="다자녀가구 통행료 할인 신청",
                source="blackkiwi_daily",
                rank=12,
                windows=("24h",),
            ),
        ]
        stale_score = score_group(stale, news_count=5, coherence=0.70)
        fresh_score = score_group(fresh, news_count=5, coherence=0.70)
        self.assertGreater(fresh_score, stale_score)


if __name__ == "__main__":
    unittest.main()
