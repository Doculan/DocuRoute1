"""The three documents generated when a proposal locks.

Order matters only for reading the result: the form, the draft copy it
points to, then the annex it may refer to.

**Absolute imports for anything outside this package** (`from api.models`,
never `from ..models`). `api/` has no `__init__.py`, so test discovery
treats it as the top level and imports this package as plain
`generation`; a relative import reaching above it then fails. The other
sub-package, `api/management`, follows the same rule.
"""

from . import annex, dcr, pages

GENERATORS = [dcr.generate, pages.generate, annex.generate]
