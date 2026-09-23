"""The documents a request produces, and the number it carries.

Phase 3a builds the machinery and the record; phase 3b fills in the
generators that actually write files.

Three rules shape it.

**Generated once, at the moment the content freezes.** Not on demand, and
never regenerated. The content cannot change after the lock, so a second
generation could only repeat itself - or, if it did not, the paper in
somebody's hand and the record in the system would disagree, with no way
to tell which was right.

**All of it, or none of it.** Generation runs inside the transaction that
locks the proposal, so a generator that fails takes the lock down with it.
A proposal frozen with nothing to sign would be a dead end that nobody
could act on and nobody could undo.

> A rollback undoes the rows, not the bytes. If one generator writes its
> file and a later one fails, the file stays on disk with no row pointing
> at it. Harmless - nothing reads an attachment except through its row -
> but untidy, and worth a sweep once 3b has real generators to orphan
> anything.

**The system does not verify anything.** It fills a form from what it
already holds and records what was uploaded. Whether the right document
was signed, by the right person, is checked by the QMS office against the
physical copies.
"""

from django.db import transaction

from .models import Attachment, Proposal


# ─── The DCR number ──────────────────────────────────────────

# PROVISIONAL - pending confirmation from the QMS office, which has not
# yet told us the format it uses on paper. One constant, one place to
# change, and `allocate` below is the only thing that reads it.
DCR_NUMBER_FORMAT = 'DCR-{year}-{sequence:03d}'
DCR_NUMBER_PREFIX = 'DCR-{year}-'


def allocate_dcr_number(when=None):
    """The next number for the year, as a string.

    Counted per year from the numbers already issued rather than from a
    stored counter, so restoring a backup cannot hand out a number twice.
    The partial unique index on `Proposal.dcr_number` is the backstop: two
    locks racing for the same number make the second one fail loudly
    instead of quietly duplicating.

    Call inside the locking transaction.
    """
    from django.utils import timezone

    when = when or timezone.now()
    year = timezone.localtime(when).year if timezone.is_aware(when) else when.year
    prefix = DCR_NUMBER_PREFIX.format(year=year)

    issued = Proposal.objects.filter(
        dcr_number__startswith=prefix
    ).values_list('dcr_number', flat=True)

    highest = 0
    for number in issued:
        tail = number[len(prefix):]
        if tail.isdigit():
            highest = max(highest, int(tail))

    return DCR_NUMBER_FORMAT.format(year=year, sequence=highest + 1)


# ─── Generation ──────────────────────────────────────────────

# Each entry takes (proposal, version, actor) and returns the Attachment
# rows it created: the DCR, the draft copy, and the annex when there is
# something to put in it. Tests replace this list to exercise the
# machinery on its own.
from .generation import GENERATORS  # noqa: E402


def generate_package(proposal, version, actor):
    """Make the documents to be signed. Returns what it created.

    Must be called inside a transaction - see the module docstring. The
    assertion is not defensive tidiness: without it a generator failing
    half way would leave a frozen proposal holding two of its three
    documents, and no screen would have a way to say so.
    """
    if transaction.get_autocommit():
        # Deliberately not an `assert`: under `python -O` the assertion
        # would vanish and the protection with it, leaving exactly the
        # half-documented frozen proposal this guard exists to prevent.
        raise RuntimeError(
            'generate_package must run inside the transaction that locks '
            'the proposal, so a failure takes the lock with it'
        )

    made = []
    for generate in GENERATORS:
        made.extend(generate(proposal, version, actor) or [])
    return made


def package_is_complete(proposal, version):
    """Whether every document this request needs has been generated.

    Read from the rows rather than from the status, so the two cannot
    drift apart. With no generators registered this is false, and the
    proposal correctly stays `LOCKED`. The annex is not required: it
    exists only when there was concurrence or an over-long reason.
    """
    if not GENERATORS:
        return False

    have = set(
        Attachment.objects.filter(
            version=version, superseded_at__isnull=True,
            kind__in=Attachment.GENERATED_KINDS,
        ).values_list('kind', flat=True)
    )
    return Attachment.DCR_GENERATED in have and Attachment.PAGES_GENERATED in have


def scans_outstanding(proposal, version):
    """The signed copies still to be uploaded before the IMR can look.

    The DCR itself always; the draft copy too, because the form asks for
    it to be attached and section 2 refers to it rather than repeating it.
    """
    have = set(
        Attachment.objects.filter(
            version=version, superseded_at__isnull=True,
            kind__in=Attachment.SCAN_KINDS,
        ).values_list('kind', flat=True)
    )
    return [k for k in (Attachment.SIGNED_DCR, Attachment.SIGNED_PAGES)
            if k not in have]
