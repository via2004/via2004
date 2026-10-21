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
    width = max(1000, 120 + len(months) * 72)
    height = 330
    left, right, top, bottom = 64, width - 30, 92, 274
    maximum = max(months.values()) or 1
    step = max(1, 10 ** math.floor(math.log10(maximum / 3)))
    for multiplier in (1, 2, 5, 10):
        candidate = step * multiplier
        if maximum / candidate <= 3:
            step = candidate
            break
    ceiling = math.ceil(maximum / step) * step
    plot_height = bottom - top
    spacing = (right - left) / len(months)
    bar_width = min(38, spacing * 0.34)
    single_year = len({m[:4] for m in months}) == 1
    year_label = first[:4] if single_year else first[:4] + '—' + now.strftime('%Y')
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
             '<title id="title">活动时长</title>',
             '<desc id="desc">横轴为月份，纵轴为活动小时数。历史时长由本地日志估算，后续每日数据来自 WakaTime。</desc>',
             f'<rect width="{width}" height="{height}" fill="#0d1117"/>',
             '<g font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Arial, Noto Sans CJK SC, sans-serif">',
             '<text x="30" y="41" fill="#dce1e7" font-size="20" font-weight="500">活动时长</text>',
             f'<text x="{width-30}" y="40" fill="#8b949e" font-size="12" text-anchor="end">{year_label} · 小时</text>']
    for tick in range(int(ceiling / step) + 1):
        value = tick * step
        y = bottom - value / ceiling * plot_height
        parts += [f'<line x1="{left}" y1="{y:.2f}" x2="{right}" y2="{y:.2f}" stroke="#252c34" stroke-width="0.7"/>',
                  f'<text x="{left-22}" y="{y+4:.2f}" fill="#727d88" text-anchor="end" font-size="11">{value:g}</text>']
    for i, (month, hours) in enumerate(sorted(months.items())):
        center = left + spacing * (i + 0.5)
        bar_height = hours / ceiling * plot_height
        y = bottom - bar_height
        current = month == end
        color = '#d5dde5' if current else '#82909e'
        label_color = '#d5dde5' if current else '#8b97a3'
        if hours:
            # Square bases meet the baseline; only the top corners are softened.
            x, r = center - bar_width / 2, min(3, bar_height / 2)
            path = f'M {x:.2f},{bottom} V {y+r:.2f} Q {x:.2f},{y:.2f} {x+r:.2f},{y:.2f} H {x+bar_width-r:.2f} Q {x+bar_width:.2f},{y:.2f} {x+bar_width:.2f},{y+r:.2f} V {bottom} Z'
            parts.append(f'<path d="{path}" fill="{color}"><title>{month}：{hours:.1f} 小时</title></path>')
        label = str(int(month[5:])) + '月' if single_year else month.replace('-', '.')
        parts += [f'<text x="{center:.2f}" y="{y-10:.2f}" fill="{label_color}" text-anchor="middle" font-size="12">{hours:.1f}</text>',
                  f'<text x="{center:.2f}" y="{bottom+27}" fill="{label_color}" text-anchor="middle" font-size="12">{escape(label)}</text>']
    parts += ['</g></svg>']
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
