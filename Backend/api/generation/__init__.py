"""The three documents generated when a proposal locks.

Order matters only for reading the result: the form, the draft copy it
points to, then the annex it may refer to.
"""

from . import annex, dcr, pages

GENERATORS = [dcr.generate, pages.generate, annex.generate]
