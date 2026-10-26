"""Deterministic weekly cron metadata shared by builds and release tests."""
import datetime as dt
import re


BEIJING = dt.timezone(dt.timedelta(hours=8))
CRON = re.compile(r'^(\d{1,2}) (\d{1,2}) \* \* ([0-6])(?:-([0-6]))?$')


def schedule_metadata(config, fixed_clock):
    """Return the first scheduled instant strictly after an aware fixed clock.

    A missing schedule keeps archived TOML DATA compatible. Configured schedules
    must use the deliberately narrow minute/hour/weekday syntax in the brief.
    No wall clock, network access, or locale-specific weekday parsing is used.
    """
    schedule = (config or {}).get('schedule', config or {})
    if 'cron_utc' not in schedule:
        return None
    crons = schedule['cron_utc']
    late = schedule.get('late_after_minutes', 90)
    if (not isinstance(crons, list) or not crons or
            isinstance(late, bool) or not isinstance(late, int) or late < 0):
        raise ValueError('invalid_schedule')
    parsed = []
    for expression in crons:
        match = CRON.fullmatch(expression) if isinstance(expression, str) else None
        if not match:
            raise ValueError('invalid_schedule_cron')
        minute, hour, first, last = match.groups()
        minute, hour, first, last = int(minute), int(hour), int(first), int(last or first)
        if minute > 59 or hour > 23 or first > last:
            raise ValueError('invalid_schedule_cron')
        parsed.append((minute, hour, first, last))
    clock = dt.datetime.fromisoformat(fixed_clock) if isinstance(fixed_clock, str) else fixed_clock
    if getattr(clock, 'tzinfo', None) is None or not hasattr(clock, 'astimezone') or clock.utcoffset() is None:
        raise ValueError('schedule_clock_without_timezone')
    clock = clock.astimezone(dt.UTC)
    midnight = clock.replace(hour=0, minute=0, second=0, microsecond=0)
    candidates = []
    for offset in range(8):
        day = midnight + dt.timedelta(days=offset)
        weekday = (day.weekday() + 1) % 7  # Cron Sunday is 0.
        for minute, hour, first, last in parsed:
            candidate = day.replace(hour=hour, minute=minute)
            if first <= weekday <= last and candidate > clock:
                candidates.append(candidate)
    return {'cronUtc': list(crons),
            'nextRunAt': min(candidates).astimezone(BEIJING).isoformat(timespec='seconds'),
            'lateAfterMinutes': late}
