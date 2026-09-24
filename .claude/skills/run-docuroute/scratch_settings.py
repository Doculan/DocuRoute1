"""Django settings for running DocuRoute against a scratch database.

Everything as in `backend.settings`, except the database and the media
folder, which both come from the environment and must be set:

    DOCUROUTE_SCRATCH_DB     path to a *copy* of the database
    DOCUROUTE_SCRATCH_MEDIA  a folder for files the scratch run writes

The main settings can already take `SQLITE_PATH`, but not a media folder,
and locking a proposal writes three documents into `MEDIA_ROOT` - a
scratch run would otherwise leave them among the real files.

Use with PYTHONPATH pointing at this folder:
    manage.py runserver --settings=scratch_settings
"""

import os
from pathlib import Path

from backend.settings import *  # noqa: F401,F403
from backend.settings import BASE_DIR, SQLITE_OPTIONS

_db = Path(os.environ['DOCUROUTE_SCRATCH_DB']).resolve()
if _db == (Path(BASE_DIR) / 'db.sqlite3').resolve():
    raise RuntimeError('DOCUROUTE_SCRATCH_DB points at the live database. Use a copy.')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': str(_db),
        # The project's own: WAL and a 20-second wait for a lock. Without
        # them a scratch run waited 5 seconds and failed where the real
        # app would not.
        'OPTIONS': dict(SQLITE_OPTIONS),
    }
}
MEDIA_ROOT = os.environ['DOCUROUTE_SCRATCH_MEDIA']
