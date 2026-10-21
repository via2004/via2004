import unittest
from datetime import datetime, date, timezone
from unittest.mock import patch, MagicMock

from update_stats import date_range, fetch_summaries, render, replace_section, START, END


class StatisticsTests(unittest.TestCase):
    def test_seven_days_include_shanghai_today_at_utc_boundary(self):
        start, end = date_range(datetime(2026, 10, 21, 16, 1, tzinfo=timezone.utc))
        self.assertEqual((start, end), (date(2026, 10, 16), date(2026, 10, 22)))

    def test_aggregate_daily_metrics_and_keep_cached_tokens_separate(self):
        rows = [
            {'grand_total': {'total_seconds': 3600, 'ai_additions': 20,
                             'ai_input_tokens': 100, 'ai_cached_input_tokens': 200},
             'categories': [{'name': 'AI Coding', 'total_seconds': 1800}]},
            {'grand_total': {'total_seconds': 1800, 'ai_additions': 30,
                             'ai_input_tokens': 50, 'ai_cached_input_tokens': 300},
             'categories': [{'name': 'AI Coding', 'total_seconds': 1800}]},
        ]
        result = render(rows, date(2026, 10, 16), date(2026, 10, 22),
                        datetime(2026, 10, 22, tzinfo=timezone.utc))
        for expected in ['1 小时 30 分钟', 'AI Coding：**1 小时 0 分钟**',
                         'AI 新增 **50**', '输入 Token：**150**', '缓存输入：**500**']:
            self.assertIn(expected, result)

    def test_partial_response_does_not_replace_previous_readme(self):
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        with patch('update_stats.urlopen', return_value=response), patch('update_stats.json.load', return_value={'data': []}):
            with self.assertRaisesRegex(ValueError, 'incomplete date range'):
                fetch_summaries('test-placeholder', date(2026, 10, 16), date(2026, 10, 22))
        original = 'intro\n' + START + '\nold\n' + END + '\nfooter'
        self.assertEqual(replace_section(original, 'new'), 'intro\n' + START + '\nnew\n' + END + '\nfooter')
        with self.assertRaises(ValueError):
            replace_section(original + START, 'new')


if __name__ == '__main__':
    unittest.main()
