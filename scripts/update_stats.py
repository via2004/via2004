"""Render seven calendar days, including today, from WakaTime daily summaries."""

import base64
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

START = '<!--START_SECTION:waka-->'
END = '<!--END_SECTION:waka-->'
TIMEZONE = ZoneInfo('Asia/Shanghai')


def date_range(now):
    end = now.astimezone(TIMEZONE).date()
    return end - timedelta(days=6), end


def fetch_summaries(key, start, end):
    query = urlencode({'start': str(start), 'end': str(end), 'timezone': str(TIMEZONE)})
    auth = ('Bearer ' + key if key.startswith('waka_tok_') else
            'Basic ' + base64.b64encode((key + ':').encode()).decode())
    request = Request('https://api.wakatime.com/api/v1/users/current/summaries?' + query,
                      headers={'Authorization': auth, 'Cache-Control': 'no-cache'})
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


def render(rows, start, end, now):
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
    lines += ['<sub>历史回补只涵盖采集器实际读取的记录；此前未安装编辑器采集插件的人工编程活动无法补齐。</sub>', '',
              f'最后更新：{now.astimezone(TIMEZONE):%Y-%m-%d %H:%M:%S}（北京时间）']
    return '\n'.join(lines)


def replace_section(original, block):
    if original.count(START) != 1 or original.count(END) != 1:
        raise ValueError('README must contain exactly one pair of WakaTime markers.')
    before, rest = original.split(START)
    _, after = rest.split(END)
    return before + START + '\n' + block + '\n' + END + after


def main():
    key = os.environ.get('WAKATIME_API_KEY', '').strip()
    if not key:
        raise ValueError('Missing WAKATIME_API_KEY; keeping previous statistics.')
    now = datetime.now(TIMEZONE)
    start, end = date_range(now)
    rows = fetch_summaries(key, start, end)
    path = Path(__file__).resolve().parents[1] / 'README.md'
    updated = replace_section(path.read_text(), render(rows, start, end, now))
    path.write_text(updated)
    print(f'Updated statistics for {start} through {end}.')


if __name__ == '__main__':
    try:
        main()
    except HTTPError as error:
        print(f'WakaTime API returned HTTP {error.code}; README unchanged.', file=sys.stderr)
        sys.exit(1)
    except (ValueError, URLError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
