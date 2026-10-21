"""Persist daily aggregates and render a self-contained GitHub SVG."""

from collections import defaultdict
from datetime import datetime
from html import escape
import math
import json


def archive_days(existing, rows):
    result = dict(existing)
    fields = ('total_seconds', 'ai_additions', 'ai_deletions', 'human_additions',
              'human_deletions', 'ai_input_tokens', 'ai_cached_input_tokens',
              'ai_output_tokens', 'ai_prompt_events_total', 'ai_model_total_cost')
    for row in rows:
        total = row['grand_total']
        result[row['range']['date']] = {
            **{key: total.get(key, 0) for key in fields},
            'ai_seconds': sum(item['total_seconds'] for item in row.get('categories', [])
                              if item['name'] == 'AI Coding'),
        }
    return dict(sorted(result.items()))


def combined_days(baseline, daily):
    # Keep the local estimate and the daily service statistics disjoint by date.
    cutoff = baseline['cutoff_exclusive']
    result = {day: value['estimated_ai_seconds'] for day, value in baseline['days'].items()
              if day < cutoff}
    result.update({day: value['ai_seconds'] for day, value in daily.items() if day >= cutoff})
    return dict(sorted(result.items()))


def history_svg(baseline, daily, now):
    days = combined_days(baseline, daily)
    months = defaultdict(float)
    for day, seconds in days.items():
        months[day[:7]] += seconds / 3600
    first = min(days)
    # Include inactive months so the timeline never conceals gaps.
    year, month = map(int, first[:7].split('-'))
    end = now.strftime('%Y-%m')
    while f'{year:04}-{month:02}' <= end:
        months.setdefault(f'{year:04}-{month:02}', 0)
        month += 1
        if month == 13:
            year, month = year + 1, 1
    width = max(1000, 130 + len(months) * 74)
    height = 440
    left, right, top, bottom = 76, width - 36, 102, 360
    maximum = max(months.values()) or 1
    step = max(1, 10 ** math.floor(math.log10(maximum / 4)))
    for multiplier in (1, 2, 5, 10):
        candidate = step * multiplier
        if maximum / candidate <= 5:
            step = candidate
            break
    ceiling = math.ceil(maximum / step) * step
    plot_height = bottom - top
    spacing = (right - left) / len(months)
    bar_width = min(62, spacing * 0.52)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
             '<title id="title">活动时长</title>',
             '<desc id="desc">横轴为月份，纵轴为活动小时数。历史时长由本地日志估算，后续每日数据来自 WakaTime。</desc>',
             '<defs><linearGradient id="bar" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#6ddac5"/><stop offset="1" stop-color="#379a91"/></linearGradient></defs>',
             f'<rect x="1" y="1" width="{width-2}" height="{height-2}" rx="14" fill="#0d1117" stroke="#30363d"/>',
             '<g font-family="Arial, Noto Sans CJK SC, sans-serif">',
             '<text x="32" y="48" fill="#e6edf3" font-size="24" font-weight="600">活动时长</text>',
             '<text x="38" y="88" fill="#8b949e" font-size="12">小时</text>']
    for tick in range(int(ceiling / step) + 1):
        value = tick * step
        y = bottom - value / ceiling * plot_height
        parts += [f'<line x1="{left}" y1="{y:.2f}" x2="{right}" y2="{y:.2f}" stroke="#21262d"/>',
                  f'<text x="{left-18}" y="{y+4:.2f}" fill="#8b949e" text-anchor="end" font-size="12">{value:g}</text>']
    for i, (month, hours) in enumerate(sorted(months.items())):
        center = left + spacing * (i + 0.5)
        bar_height = hours / ceiling * plot_height
        y = bottom - bar_height
        if hours:
            parts.append(f'<rect x="{center-bar_width/2:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{bar_height:.2f}" rx="5" fill="url(#bar)"/>')
        parts += [f'<text x="{center:.2f}" y="{y-12:.2f}" fill="#c9d1d9" text-anchor="middle" font-size="14" font-weight="500">{hours:.1f}</text>',
                  f'<text x="{center:.2f}" y="{bottom+28}" fill="#8b949e" text-anchor="middle" font-size="13">{escape(month)}</text>']
    parts += [f'<text x="{(left+right)/2:.2f}" y="{height-18}" fill="#8b949e" text-anchor="middle" font-size="12">月份</text>', '</g></svg>']
    return '\n'.join(parts)


def history_block(baseline):
    days = baseline['days']
    return '\n'.join([
        '![按月活动时长](assets/coding-history.svg)', '',
        '<details><summary>统计口径与历史数据</summary>', '',
        f'历史记录：**{min(days)} — {max(days)}**。按本地 Codex 日志估算；之后的活动按天保存，持续累计。', '',
        '- 合并同一会话的所有日志片段；相邻活动间隔不超过 15 分钟时计入时长，并行会话的重叠时间只算一次。',
        '- 此历史时长为活动估算，不代表精确工时；没有日志的时段不推算。',
        '- 从历史回溯截止日之后接入 WakaTime 每日统计，两段按日期分开，不重复相加。',
        '- 旧日志不用于推算此前未采集的人工编程时间。',
        '- [历史汇总](data/history-baseline.json) · [每日统计归档](data/daily-stats.json)', '',
        '</details>', '', '### 最近活动', '',
    ])


def prepare_history(root, rows, now):
    path = root / 'data' / 'daily-stats.json'
    existing = json.loads(path.read_text()) if path.exists() else {}
    daily = archive_days(existing, rows)
    baseline_path = root / 'data' / 'history-baseline.json'
    baseline = json.loads(baseline_path.read_text())
    return daily, history_svg(baseline, daily, now), history_block(baseline)
