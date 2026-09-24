"""Prepare a scratch copy of the demo data for the end-to-end drives.

The demo organisation (`manage.py seed_demo_org`) is fictional. On a
scratch copy only: turn access by position on, and check that the demo
accounts the drives use still sign in with the demo password.
"""
from django.conf import settings
assert 'scratch' in settings.SETTINGS_MODULE, 'run with --settings=scratch_settings'
from django.contrib.auth import authenticate
from api.models import AccessMode, Manual, Proposal

AccessMode.objects.update_or_create(pk=1, defaults={'by_position': True})
for name in ('ACC_Juan', 'ACC_Maria', 'BUD_Jose', 'CMO_Carlo', 'BUD_Rosa', 'QMS_Ana', 'QMS_Pedro'):
    print(name, 'ok' if authenticate(username=name, password='Office123!') else 'PASSWORD DIFFERS')
for title in ('FAM 6.02', 'FAM 6.03', 'FAM 6.01', 'FAM 5.01', 'FAM 4.02'):   # one per path
    manual = Manual.objects.get(title=title)
    if manual.statuses.exists() or Proposal.objects.filter(manual=manual).exists():
        raise SystemExit(f'{title} has been used already. Start again from a fresh copy.')
print('ready')
