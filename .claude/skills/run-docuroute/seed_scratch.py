"""Scratch people and one proposal awaiting signature, for driving the app.

Run inside `manage.py shell --settings=scratch_settings -c "exec(open(...).read())"`
(the interactive shell cannot take blank lines inside a block). Refuses to
run against anything but a scratch database. Fictional offices and people
only, all named "Verify ...".

Leaves:
    verify_enc / verify_head   Encoder and Head of "Verify Accounting Office"
    verify_bud_head            Head of "Verify Budget Office" (has concurred)
    verify_admin               a system admin
    all with the password Verify-scratch-pass!
    one proposal on "VRF 1.01", locked, its documents generated, awaiting
    signature.
"""
import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

assert 'scratch' in settings.SETTINGS_MODULE, 'run with --settings=scratch_settings'

from api.concurrence_views import _lock
from api.models import (
    AccessMode, Concurrence, CustomUser, Department, Manual, ManualSection,
    Office, Position, PositionAssignment, Proposal, ProposalParticipant,
    ProposalVersion, SectionChange,
)

PASSWORD = 'Verify-scratch-pass!'
TODAY = timezone.localdate()


def person(name, office=None, kind=None, **fields):
    defaults = {'is_approved': True, 'role': 'staff', 'system_role': 'user'}
    defaults.update(fields)
    user, _ = CustomUser.objects.get_or_create(username=name, defaults=defaults)
    user.set_password(PASSWORD)
    user.save()
    position = None
    if office is not None:
        position, _ = Position.objects.get_or_create(office=office, kind=kind)
        PositionAssignment.objects.get_or_create(
            user=user, position=position,
            defaults={'starts_on': TODAY - datetime.timedelta(days=30)})
    return user, position


if Manual.objects.filter(title='VRF 1.01').exists():
    raise SystemExit('Already seeded. Start again from a fresh copy of the database.')

with transaction.atomic():
    AccessMode.objects.update_or_create(pk=1, defaults={'by_position': True})
    top = Office.objects.create(name='Verify VP Office', is_approving_level=True)
    acc = Office.objects.create(name='Verify Accounting Office', parent=top)
    bud = Office.objects.create(name='Verify Budget Office', parent=top)
    manual = Manual.objects.create(
        title='VRF 1.01', department=Department.objects.create(name='verify-scratch'))
    section = ManualSection.objects.create(
        manual=manual, subtitle='3.0 POLICIES', order=0, tag='POLICY',
        content='The Cashier shall release the cheque within five days.')

    encoder, _ = person('verify_enc', acc, Position.ENCODER)
    head, _ = person('verify_head', acc, Position.HEAD)
    bud_head, bud_position = person('verify_bud_head', bud, Position.HEAD)
    person('verify_admin', role='admin', system_role='system_admin')

    proposal = Proposal.objects.create(
        manual=manual, initiating_office=acc, created_by=encoder,
        status=Proposal.CONCURRENCE)
    ProposalParticipant.objects.create(
        proposal=proposal, office=bud, office_name_at_time=bud.name,
        role=ProposalParticipant.CONCURRING)
    ProposalParticipant.objects.create(
        proposal=proposal, office=top, office_name_at_time=top.name,
        role=ProposalParticipant.APPROVING, route_order=0)
    # No AI check is attached, so the section shows "needs a check". The
    # real flow cannot reach this point without one; that is expected here.
    version = ProposalVersion.objects.create(
        proposal=proposal, number=1,
        overall_reason='Consolidated the release window after the 2026 management review.',
        submitted_by=head, submitted_at=timezone.now())
    SectionChange.objects.create(
        version=version, section=section, old_text=section.content,
        new_text='The Cashier shall release the cheque within one working day.')
    Concurrence.objects.create(
        version=version, office=bud, decision=Concurrence.CONCUR,
        recorded_by=bud_head, recorded_by_position=bud_position)
    _lock(proposal, version, bud_head, bud, detail='scratch seed')

proposal.refresh_from_db()
print('SEEDED proposal', proposal.id, proposal.status, proposal.dcr_number)
