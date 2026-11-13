"""Validate the repository settings used to collect and render market data."""
import datetime as dt
import re

from release_schedule import schedule_metadata, validate_late_after_minutes


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def err(self, where, message):
        self.errors.append(f'[错误] {where}：{message}')

    def warn(self, where, message):
        self.warnings.append(f'[提醒] {where}：{message}')


def validate_market_config(config, today):
    report = Report()
    schedule = config.get('schedule', {})
    try:
        if not isinstance(schedule, dict):
            raise ValueError('invalid_schedule')
        # Validate this file without falling back to the installed schedule.
        validate_late_after_minutes(schedule.get('late_after_minutes'))
        if schedule_metadata(schedule, dt.datetime.combine(today, dt.time(), dt.UTC)) is None:
            raise ValueError('invalid_schedule')
    except ValueError:
        report.err('config.toml [schedule]', '需要有效 cron_utc 和 0–180 的整数 late_after_minutes')

    site = config.get('site', {})
    repo_url = str(site.get('repo_url', '')).strip().rstrip('/')
    if repo_url and not re.fullmatch(r'https://github\.com/[^/]+/[^/]+', repo_url):
        report.err('config.toml [site]', f'repo_url 应形如 https://github.com/用户名/仓库名，现在是 {repo_url!r}')
    kb_branch = str(site.get('kb_branch', 'main')).strip() or 'main'
    indices = config.get('index', [])
    if not indices:
        report.warn('config.toml', '没有配置 [[index]]，跑马灯将不显示指数')
    for i, row in enumerate(indices, start=1):
        if not row.get('symbol') or not row.get('name'):
            report.err(f'config.toml [[index]] 第{i}个', '需要 symbol 和 name')

    return {'config': {'title': site.get('title', '投研雷达'), 'repo_url': repo_url,
                       'kb_branch': kb_branch, 'indices': indices, 'fx_fallback': config.get('fx_fallback', {}),
                       'ratio': config.get('ratio', {}), 'schedule': schedule}}, report
