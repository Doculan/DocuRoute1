"""Tests never write into the real media folder.

Locking a proposal generates three documents, and a test that locks one
would otherwise leave them in `media/proposals/` beside the university's
real files - where the next person to look would not know which were
which. The whole run gets a temporary `MEDIA_ROOT`, removed afterwards.

The document templates are read from beside `MEDIA_ROOT`, not under it
(see `api.generation.common`), so they are still found.
"""

import shutil
import tempfile

from django.test.runner import DiscoverRunner
from django.test.utils import override_settings


class TemporaryMediaRunner(DiscoverRunner):

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._media = tempfile.mkdtemp(prefix='docuroute-test-media-')
        self._override = override_settings(MEDIA_ROOT=self._media)
        self._override.enable()

    def teardown_test_environment(self, **kwargs):
        self._override.disable()
        shutil.rmtree(self._media, ignore_errors=True)
        super().teardown_test_environment(**kwargs)
