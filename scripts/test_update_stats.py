import unittest
import tempfile
from pathlib import Path
import json
from datetime import datetime, date, timezone
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

from update_stats import date_range, fetch_summaries, render, replace_section, read_access_token, main, START, END


class StatisticsTests(unittest.TestCase):
    def test_read_token_rejects_missing_secret_and_upload_api_key(self):
        for env in [{}, {'WAKATIME_ACCESS_TOKEN': 'waka_test_upload_only'}]:
            with self.assertRaises(ValueError) as caught:
                read_access_token(env)
            self.assertNotIn('waka_test_upload_only', str(caught.exception))
        self.assertEqual(read_access_token({'WAKATIME_ACCESS_TOKEN': ' waka_tok_test '}), 'waka_tok_test')

    def test_oauth_bearer_header_and_no_token_in_url(self):
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        payload = {'data': [{'range': {'date': '2026-11-02'}, 'grand_total': {}}]}
        with patch('update_stats.urlopen', return_value=response) as opened, patch('update_stats.json.load', return_value=payload):
            fetch_summaries('waka_tok_test', date(2026, 11, 2), date(2026, 11, 2))
        request = opened.call_args.args[0]
        self.assertEqual(request.get_header('Authorization'), 'Bearer waka_tok_test')
        self.assertNotIn('waka_tok_test', request.full_url)

    def test_permission_denied_preserves_all_generated_files(self):
        with tempfile.TemporaryDirectory() as tmp, patch('update_stats.ROOT', Path(tmp)), \
             patch.dict('os.environ', {'WAKATIME_ACCESS_TOKEN': 'waka_tok_test'}), \
             patch('update_stats.urlopen', side_effect=HTTPError('https://api.wakatime.com', 403, 'Forbidden', {}, None)), \
             patch('update_stats.Path.write_text') as write:
            with self.assertRaises(HTTPError):
                main()
            write.assert_not_called()

    def test_cached_wakatime_failure_still_updates_local_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            (root / 'README.md').write_text(START + '\nold\n' + END)
            cache = {'start': '2026-11-01', 'end': '2026-11-01', 'fetched_at': 'old-fetch',
                     'rows': [{'range': {'date': '2026-11-01'}, 'grand_total': {}}]}
            (root / 'data/wakatime-week.json').write_text(json.dumps(cache))
            local = {'schema_version': 2, 'days': {'2026-11-01': {'estimated_ai_seconds': 7786}}}
            (root / 'data/codex-activity.json').write_text(json.dumps(local))
            with patch('update_stats.ROOT', root), \
                 patch.dict('os.environ', {'WAKATIME_ACCESS_TOKEN': 'waka_tok_test'}), \
                 patch('update_stats.urlopen', side_effect=HTTPError('https://api.wakatime.com', 403, 'Forbidden', {}, None)), \
                 patch('update_stats.prepare_history', return_value=({}, '<svg/>', 'local history\n')):
                main()
            self.assertIn('本地日志估算', (root / 'README.md').read_text())
            self.assertIn('old-fetch', (root / 'README.md').read_text())
            self.assertEqual(json.loads((root / 'data/wakatime-week.json').read_text()), cache)

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
