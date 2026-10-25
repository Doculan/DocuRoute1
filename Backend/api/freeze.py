"""The change freeze (spec §6.6, Phase 3D): what it blocks, decided once.

A freeze says "do not revise now" - a separate control from a deadline.
While one is in force (started, not lifted) it blocks, within its scope:

| Action | During a freeze |
|---|---|
| Starting a new proposal | refused |
| Send to Head | refused |
| Submit to concurrence | refused |
| Making effective | refused |
| Editing and saving drafts, running checks | allowed |
| Concurring and returning on proposals already in concurrence | allowed |
| Signing, scans, the IMR's decision | allowed; only making effective waits |
| Reading anything | never blocked |
| The admin's direct edits, adding, deleting, merging or splitting sections, deleting a manual | refused |
| Commands that rewrite section text (`reextract_manuals`, `clean_section_content`, `import_mastercopies --replace`) | skip frozen manuals unless `--ignore-freeze` |

**Scope:** everything, selected offices (the office making the proposal),
or selected manual series (the proposal's document). A direct write has no
proposing office: it is covered by everything, by the document's series,
or by an office that concurs on the document. An **exception**
names one proposal or one manual it lets through. Several freezes may be
in force; any one covering an action blocks it.

**Deadlines inside a freeze:** overdue, escalation and the weekly repeat
are paused for what it covers (`deadline_ladder.plan`), and resume -
caught up - once it is lifted.
"""

from collections import namedtuple

from rest_framework.response import Response

from .models import Freeze, FreezeException, FreezeTarget

START, SEND_TO_HEAD, SUBMIT, MAKE_EFFECTIVE = 'start', 'send_to_head', 'submit', 'make_effective'
EDIT, ADD, DELETE_SECTION, DELETE_MANUAL, RESTRUCTURE = (
    'edit', 'add', 'delete_section', 'delete_manual', 'restructure')
WAITS = {
    START: 'Starting a new proposal',
    SEND_TO_HEAD: 'Sending to the Head',
    SUBMIT: 'Submitting',
    MAKE_EFFECTIVE: 'Making it effective',
    EDIT: 'Editing it directly',
    ADD: 'Adding sections',
    DELETE_SECTION: 'Deleting a section',
    DELETE_MANUAL: 'Deleting the manual',
    RESTRUCTURE: 'Merging or splitting sections',
}


# A manual owed, as `InForce.pausing` needs it: its id and its series.
Owed = namedtuple('Owed', 'pk series_id')


class InForce:
    """The freezes in force now, with what each covers. Two queries, made
    once per request or run."""

    def __init__(self):
        self.freezes = list(Freeze.objects.filter(lifted_at__isnull=True).order_by('started_at'))
        self.offices, self.series = {}, {}
        if self.freezes:
            for freeze_id, office_id, series_id in FreezeTarget.objects.filter(
                    freeze__in=self.freezes).values_list('freeze_id', 'office_id', 'series_id'):
                if office_id:
                    self.offices.setdefault(freeze_id, set()).add(office_id)
                if series_id:
                    self.series.setdefault(freeze_id, set()).add(series_id)

    def __bool__(self):
        return bool(self.freezes)

    def _covers(self, freeze, office_ids, series_ids):
        return (freeze.scope == Freeze.ALL
                or office_ids & self.offices.get(freeze.pk, set())
                or series_ids & self.series.get(freeze.pk, set()))

    def covering(self, office_ids=(), series_ids=()):
        """The first freeze covering any of these offices or series."""
        office_ids, series_ids = set(office_ids) - {None}, set(series_ids) - {None}
        for freeze in self.freezes:
            if self._covers(freeze, office_ids, series_ids):
                return freeze
        return None

    def excepted_manuals(self):
        """{freeze id: manual ids excepted}. One query, on first use."""
        if not hasattr(self, '_excepted'):
            self._excepted = {}
            for freeze_id, manual_id in FreezeException.objects.filter(
                    freeze__in=self.freezes, manual__isnull=False,
            ).values_list('freeze_id', 'manual_id'):
                self._excepted.setdefault(freeze_id, set()).add(manual_id)
        return self._excepted

    def pausing(self, office_id, manuals):
        """The freeze pausing a deadline unit's overdue notices: one
        covering the owing office or a manual owed, unless every manual
        owed has an exception from it."""
        office_ids = {office_id}
        series_ids = {m.series_id for m in manuals} - {None}
        for freeze in self.freezes:
            if not self._covers(freeze, office_ids, series_ids):
                continue
            excepted = self.excepted_manuals().get(freeze.pk, set())
            if manuals and all(m.pk in excepted for m in manuals):
                continue
            return freeze
        return None


def payload(freeze):
    if freeze is None:
        return None
    return {'id': freeze.pk, 'reason': freeze.reason,
            'expected_end_on': freeze.expected_end_on, 'scope': freeze.scope}


def blocking(proposal=None, manual=None, office=None, in_force=None):
    """The freeze that blocks changing this, or None - after exceptions."""
    in_force = in_force if in_force is not None else InForce()
    if not in_force:
        return None
    manual = manual or (proposal.manual if proposal is not None else None)
    office_id = office.pk if office is not None else (
        proposal.initiating_office_id if proposal is not None else None)
    freeze = in_force.covering([office_id], [manual.series_id if manual is not None else None])
    if freeze is None:
        return None
    exceptions = FreezeException.objects.filter(freeze=freeze)
    if proposal is not None and exceptions.filter(proposal=proposal).exists():
        return None
    if manual is not None and exceptions.filter(manual=manual).exists():
        return None
    return freeze


def refusal(action, proposal=None, manual=None, office=None):
    """A 409 saying why and until when, or None."""
    return _refused(action, blocking(proposal, manual, office))


def direct_blocking(manual, in_force=None):
    """The freeze that blocks writing to this document directly, or None:
    one over everything, its series, or an office that concurs on it -
    unless the manual has an exception from it."""
    from .org_tree import concurring_offices_of
    in_force = in_force if in_force is not None else InForce()
    if not in_force:
        return None
    offices = concurring_offices_of([manual.pk]).get(manual.pk, [])
    office_ids, series_ids = set(offices), {manual.series_id} - {None}
    for freeze in in_force.freezes:
        if (in_force._covers(freeze, office_ids, series_ids)
                and manual.pk not in in_force.excepted_manuals().get(freeze.pk, set())):
            return freeze
    return None


def direct_refusal(action, manual):
    """For the admin's direct writes: a 409 saying why and until when, or None."""
    return _refused(action, direct_blocking(manual))


def frozen_skip(command, manual, options):
    """For a management command about to rewrite a manual's text: True
    (named on stderr) when a change freeze covers it and the command was
    not run with `--ignore-freeze`. With the flag it is written, and said."""
    held = direct_blocking(manual)
    if held is None:
        return False
    if options.get('ignore_freeze'):
        command.stderr.write(f'  {manual.title}: under a change freeze '
                             f'("{held.reason}"); written anyway (--ignore-freeze)')
        return False
    command.stderr.write(f'  {manual.title}: skipped - frozen for audit until '
                         f'{held.expected_end_on:%d %b %Y} ("{held.reason}"). '
                         f'Run with --ignore-freeze to write it anyway.')
    return True


def _refused(action, freeze):
    if freeze is None:
        return None
    return Response({
        'error': (f'Frozen for audit until {freeze.expected_end_on:%d %b %Y}: {freeze.reason}. '
                  f'{WAITS[action]} waits until the freeze is lifted.'),
        'reason': 'frozen',
        'freeze': payload(freeze),
    }, status=409)


def for_viewer(user, in_force=None):
    """The freeze to show this person in the action row: one covering
    their offices, or - for the admin and QMS staff, who act across
    offices - any in force."""
    from . import access
    in_force = in_force if in_force is not None else InForce()
    if not in_force:
        return None
    if access.reads_everything(user):
        return in_force.freezes[0]
    return in_force.covering([o.pk for o in access.current_offices(user)])
