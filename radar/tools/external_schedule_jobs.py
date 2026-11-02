"""Print credential-free, disabled cron-job.org job templates. Never sends HTTP.

API field definitions: https://docs.cron-job.org/rest-api.html
Dispatch API: https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from schedule_admission import REPOSITORY, SOURCE_BRANCH, SLOTS


def job_templates():
    jobs = []
    for key, (_, hour, minute, days) in SLOTS.items():
        jobs.append({'slot': key, 'job': {
            'title': 'research-radar ' + key,
            'enabled': False,
            'saveResponses': False,
            'url': f'https://api.github.com/repos/{REPOSITORY}/actions/workflows/radar-production.yml/dispatches',
            'requestMethod': 1,
            'requestTimeout': 30,
            'redirectSuccess': False,
            'schedule': {'timezone': 'Asia/Shanghai', 'expiresAt': 20261221000000,
                         'hours': [hour], 'minutes': [minute], 'mdays': [-1],
                         'months': [-1], 'wdays': [(day + 1) % 7 for day in days]},
            'notification': {'onFailure': False, 'onSuccess': False, 'onDisable': False,
                             'onSslCertExpiry': False, 'mode': 0},
            'extendedData': {
                # The installer must inject the repo-scoped PAT in memory. The
                # templates are intentionally unusable without that separate step.
                'headers': {'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                            'X-GitHub-Api-Version': '2026-03-10'},
                'body': json.dumps({'ref': SOURCE_BRANCH, 'inputs': {
                    'trigger': 'external_schedule', 'schedule_slot': key}}, separators=(',', ':')),
            },
        }})
    return jobs


if __name__ == '__main__':
    print(json.dumps({'jobs': job_templates(), 'enabled': False, 'containsCredentials': False}, indent=2))
