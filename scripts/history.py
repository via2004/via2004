"""Persist daily aggregates and render a self-contained GitHub SVG."""

from collections import defaultdict
from datetime import datetime
from html import escape
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
    active = len({d for d, v in baseline['days'].items() if v['activity_events'] > 0} |
                 {d for d, v in daily.items() if d >= baseline['cutoff_exclusive'] and v['ai_seconds'] > 0})
    height = 310 + 39 * len(months)
    ceiling = max(months.values()) or 1
    title = f'AI Coding 历史概览：约 {sum(days.values()) / 3600:.0f} 小时，{active} 个活跃日'
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" viewBox="0 0 1000 {height}" role="img" aria-labelledby="title desc">',
             f'<title id="title">{escape(title)}</title>',
             '<desc id="desc">历史时长由本地日志估算，后续每日数据来自 WakaTime。原始对话和代码未公开。</desc>',
             '<defs><linearGradient id="bar"><stop stop-color="#58a6ff"/><stop offset="1" stop-color="#70e1bd"/></linearGradient></defs>',
             f'<rect x="1" y="1" width="998" height="{height-2}" rx="20" fill="#0d1117" stroke="#30363d"/>',
             '<g font-family="Arial, Noto Sans CJK SC, sans-serif">',
             '<text x="34" y="42" fill="#70e1bd" font-size="13" letter-spacing="3">AI CODING · HISTORY</text>',
             '<text x="34" y="78" fill="#f0f6fc" font-size="25" font-weight="700">我的编程足迹</text>',
             f'<text x="966" y="75" fill="#8b949e" text-anchor="end" font-size="14">{first} — {now:%Y-%m-%d}</text>']
    cards = [('累计 AI 活动 · 约', f'{sum(days.values()) / 3600:,.0f}', '小时'),
             ('有记录的活跃日', str(active), '天'),
             ('本次回溯的历史会话', str(baseline['unique_sessions']), '个')]
    for i, (label, value, unit) in enumerate(cards):
        x = 34 + i * 316
        parts += [f'<rect x="{x}" y="103" width="300" height="111" rx="12" fill="#161b22" stroke="#21262d"/>',
                  f'<text x="{x+18}" y="132" fill="#8b949e" font-size="13">{label}</text>',
                  f'<text x="{x+18}" y="186" fill="#f0f6fc" font-size="40" font-weight="700">{value}<tspan fill="#8b949e" font-size="15"> {unit}</tspan></text>']
    parts.append('<text x="34" y="249" fill="#c9d1d9" font-size="14">按月活动时长</text>')
    parts.append('<text x="966" y="249" fill="#8b949e" text-anchor="end" font-size="12">历史为估算值 · 当月持续累计</text>')
    for i, (month, hours) in enumerate(sorted(months.items())):
        y = 270 + 39 * i
        width = max(2, 700 * hours / ceiling) if hours else 0
        parts += [f'<text x="34" y="{y+17}" fill="#c9d1d9" font-size="14">{month}</text>',
                  f'<rect x="131" y="{y}" width="700" height="23" rx="6" fill="#161b22"/>',
                  f'<rect x="131" y="{y}" width="{width:.2f}" height="23" rx="6" fill="url(#bar)"/>',
                  f'<text x="966" y="{y+17}" fill="#c9d1d9" text-anchor="end" font-size="14">约 {hours:.1f} 小时</text>']
    parts += [f'<text x="34" y="{height-19}" fill="#8b949e" font-size="12">本地历史日志 + 每日统计归档 · 最后更新 {now:%Y-%m-%d %H:%M}（北京时间）</text>', '</g></svg>']
    return '\n'.join(parts)


def history_block(baseline):
    days = baseline['days']
    return '\n'.join([
        '### 历史足迹', '',
        '![AI Coding 历史概览](assets/coding-history.svg)', '',
        f'历史回溯：**{min(days)} — {max(days)}**。按本地 Codex 日志估算；之后的活动按天保存，持续累计。', '',
        '<details><summary>统计口径与历史数据</summary>', '',
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
