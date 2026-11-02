"""Render seven calendar days, including today, from WakaTime daily summaries."""

from collections import defaultdict
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from history import prepare_history

START = '<!--START_SECTION:waka-->'
END = '<!--END_SECTION:waka-->'
TIMEZONE = ZoneInfo('Asia/Shanghai')
ROOT = Path(__file__).resolve().parents[1]


def read_access_token(environ):
    token = environ.get('WAKATIME_ACCESS_TOKEN', '').strip()
    if not token:
        raise ValueError(
            'Missing WAKATIME_ACCESS_TOKEN. Create a personal OAuth token at '
            'https://wakatime.com/oauth with read_summaries access and save it '
            'as the repository Actions secret WAKATIME_ACCESS_TOKEN. '
            'Keep the editor API key unchanged. Previous statistics were preserved.')
    if not token.startswith('waka_tok_'):
        raise ValueError(
            'WAKATIME_ACCESS_TOKEN must be an OAuth access token (waka_tok_), '
            'not the editor API key. Get it from https://wakatime.com/oauth. '
            'Previous statistics were preserved.')
    return token


def date_range(now):
    end = now.astimezone(TIMEZONE).date()
    return end - timedelta(days=6), end


def fetch_summaries(token, start, end):
    query = urlencode({'start': str(start), 'end': str(end), 'timezone': str(TIMEZONE)})
    request = Request('https://api.wakatime.com/api/v1/users/current/summaries?' + query,
                      headers={'Authorization': 'Bearer ' + token, 'Cache-Control': 'no-cache'})
    with urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise ValueError('WakaTime has not finished calculating summaries.')
        payload = json.load(response)
    rows = payload.get('data')
    expected = {str(start + timedelta(days=i)) for i in range((end-start).days + 1)}
    actual = [row.get('range', {}).get('date') for row in rows] if isinstance(rows, list) else []
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError('WakaTime returned an incomplete date range; keeping previous statistics.')
    if any(not isinstance(row.get('grand_total'), dict) for row in rows):
        raise ValueError('WakaTime returned an incomplete daily total.')
    return rows


def duration(seconds):
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours} 小时 {minutes} 分钟' if hours else f'{minutes} 分钟'


def clean(text):
    return str(text).replace('`', '').replace('\n', ' ').replace('\r', ' ')[:60]


def render(rows, start, end, now, local_activity=None, fetched_at=None):
    totals = defaultdict(float)
    groups = {key: defaultdict(float) for key in ('languages', 'editors', 'categories')}
    fields = ('total_seconds', 'ai_additions', 'ai_deletions', 'human_additions',
              'human_deletions', 'ai_input_tokens', 'ai_cached_input_tokens',
              'ai_output_tokens', 'ai_prompt_events_total', 'ai_model_total_cost')
    for row in rows:
        daily = row['grand_total']
        for field in fields:
            value = daily.get(field, 0)
            if not isinstance(value, (int, float)) or value < 0:
                raise ValueError('Invalid WakaTime metric: ' + field)
            totals[field] += value
        for key in groups:
            for item in row.get(key, []):
                groups[key][item['name']] += item['total_seconds']
    ai_seconds = groups['categories'].get('AI Coding', 0)
    lines = [f'**最近 7 天（含今天）：{start} — {end} · Asia/Shanghai**', '',
             f'⏱ 编程活动：**{duration(totals["total_seconds"])}**', '',
             f'🤖 AI Coding：**{duration(ai_seconds)}**', '',
             f'✍️ AI 新增 **{int(totals["ai_additions"]):,}** 行 · 删除 **{int(totals["ai_deletions"]):,}** 行', '',
             f'🧑‍💻 已采集的人工新增 **{int(totals["human_additions"]):,}** 行 · 删除 **{int(totals["human_deletions"]):,}** 行', '',
             f'🔤 输入 Token：**{int(totals["ai_input_tokens"]):,}** · 缓存输入：**{int(totals["ai_cached_input_tokens"]):,}** · 输出：**{int(totals["ai_output_tokens"]):,}**', '',
             f'💬 提示次数：**{int(totals["ai_prompt_events_total"]):,}**', '',
             f'💵 按 Token 估算费用：**${totals["ai_model_total_cost"]:,.2f}**（非订阅账单）', '']
    if local_activity:
        current_start, current_end = date_range(now)
        local_seconds = sum(v['estimated_ai_seconds'] for day, v in local_activity['days'].items()
                            if str(current_start) <= day <= str(current_end))
        lines[:6] = [f'**最近 7 天（含今天）：{current_start} — {current_end} · Asia/Shanghai**', '',
                     f'⏱ AI 活动时长（本地日志估算）：**{duration(local_seconds)}**', '',
                     '**WakaTime 采集明细**', '',
                     f'<sub>以下行数、Token 和费用仅覆盖 WakaTime 识别到的活动，可能漏掉续接日志。明细日期：{start} — {end}；采集更新：{fetched_at or "未知"}。</sub>', '']
    for title, key in [('语言', 'languages'), ('编辑器 / AI 工具', 'editors')]:
        ranked = sorted(groups[key].items(), key=lambda x: (-x[1], x[0]))[:5]
        if ranked:
            lines += [f'**{title}**', '', '```text']
            total = sum(groups[key].values())
            for name, seconds in ranked:
                percent = seconds / total * 100 if total else 0
                bar = '█' * round(percent / 5) + '░' * (20-round(percent / 5))
                lines.append(f'{clean(name)}  {duration(seconds)}  {bar} {percent:.1f}%')
            lines += ['```', '']
    lines += ['<sub>此前未安装编辑器采集插件的人工编程活动无法补齐。</sub>', '',
              f'最后更新：{now.astimezone(TIMEZONE):%Y-%m-%d %H:%M:%S}（北京时间）']
    return '\n'.join(lines)


def replace_section(original, block):
    if original.count(START) != 1 or original.count(END) != 1:
        raise ValueError('README must contain exactly one pair of WakaTime markers.')
    before, rest = original.split(START)
    _, after = rest.split(END)
    return before + START + '\n' + block + '\n' + END + after


def sanitized_rows(rows):
    # Only aggregate dimensions are published; never retain project or machine identifiers.
    result = []
    fields = ('total_seconds', 'ai_additions', 'ai_deletions', 'human_additions',
              'human_deletions', 'ai_input_tokens', 'ai_cached_input_tokens',
              'ai_output_tokens', 'ai_prompt_events_total', 'ai_model_total_cost')
    for row in rows:
        result.append({'range': {'date': row['range']['date']},
                       'grand_total': {k: row['grand_total'].get(k, 0) for k in fields},
                       **{group: [{'name': x['name'], 'total_seconds': x['total_seconds']}
                                  for x in row.get(group, [])]
                          for group in ('categories', 'languages', 'editors')}})
    return result


def main():
    now = datetime.now(TIMEZONE)
    start, end = date_range(now)
    cache_path = ROOT / 'data' / 'wakatime-week.json'
    cache = None
    fresh = False
    try:
        token = read_access_token(os.environ)
        rows = fetch_summaries(token, start, end)
        cache = {'start': str(start), 'end': str(end), 'fetched_at': now.strftime('%Y-%m-%d %H:%M:%S %Z'),
                 'rows': sanitized_rows(rows)}
        fresh = True
    except (HTTPError, URLError, ValueError) as error:
        if not cache_path.exists():
            raise
        code = f'HTTP {error.code}' if isinstance(error, HTTPError) else type(error).__name__
        print(f'::warning::WakaTime {code}; retaining its previous details while updating local activity.')
        cache = json.loads(cache_path.read_text())
        start, end = cache['start'], cache['end']
    rows = cache['rows']
    path = ROOT / 'README.md'
    local_path = ROOT / 'data' / 'codex-activity.json'
    local = json.loads(local_path.read_text()) if local_path.exists() else None
    daily, svg, intro = prepare_history(path.parent, rows, now)
    updated = replace_section(path.read_text(), intro + '\n' + render(rows, start, end, now, local, cache['fetched_at']))
    archive = path.parent / 'data' / 'daily-stats.json'
    asset = path.parent / 'assets' / 'coding-history.svg'
    archive.parent.mkdir(exist_ok=True)
    asset.parent.mkdir(exist_ok=True)
    archive.write_text(json.dumps(daily, ensure_ascii=False, indent=2) + '\n')
    asset.write_text(svg)
    if fresh:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + '\n')
    path.write_text(updated)
    print(f'Updated statistics for {start} through {end}.')


if __name__ == '__main__':
    try:
        main()
    except HTTPError as error:
        print(f'WakaTime API returned HTTP {error.code}; README unchanged.', file=sys.stderr)
        if error.code in (401, 403):
            print('Check that WAKATIME_ACCESS_TOKEN is an unexpired OAuth token '
                  'with read_summaries access: https://wakatime.com/oauth', file=sys.stderr)
        sys.exit(1)
    except (ValueError, URLError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
