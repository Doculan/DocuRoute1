"""
WSGI config for backend project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os
import threading

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

application = get_wsgi_application()


# ── Pre-warming the assessment model ──────────────────────────
#
# Loading the encoder takes about 14 seconds. Since the check moved to the
# staff side that wait no longer lands on a reviewer who chose to press a
# button - it lands on a staff member part-way through submitting, on the
# first submission after a restart. Paying it at startup instead is the
# difference between one slow page and a system that looks broken.
#
# Loaded on a background thread rather than inline, so startup is not delayed
# at all: the server begins accepting requests immediately and the model
# arrives shortly after. A check that comes in during those seconds blocks on
# the same lock it would have blocked on anyway, so nothing is worse than
# before and usually it is already done.
#
# Off by default because `runserver` restarts on every file save, and paying
# 14 seconds per save would make development miserable. Set PREWARM_MODEL=1
# for the demo and in production, where processes are long-lived.
#
# It is deliberately not wired into AppConfig.ready(): that runs for every
# management command, so `migrate`, `test` and `makemigrations` would each
# load a 700 MB model they never use. Only a WSGI server imports this file.

def _prewarm() -> None:
    try:
        from ml.revision_pipeline.pipeline import load_models
        load_models()
    except Exception:
        # A missing or broken model must not stop the server booting: the
        # pipeline already degrades to rules-only and says so. The first real
        # request will surface the problem with a message that explains it.
        pass


if os.environ.get('PREWARM_MODEL', '').strip().lower() in ('1', 'true', 'yes', 'on'):
    threading.Thread(target=_prewarm, name='prewarm-model', daemon=True).start()
