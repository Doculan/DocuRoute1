"""Needs your action: what is waiting on this person, from the data itself.

Derived from the current state of proposals and posts, not from
notifications, so it can never lose something a notice missed or a person
marked read. Each section is one aggregate query plus a short page of rows
- never a query per proposal.
"""

from django.db.models import Exists, OuterRef, Subquery
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import access, monitoring
from .models import (
    Concurrence, CustomUser, Position, PositionAssignment, Proposal,
    ProposalParticipant, ProposalVersion,
)
from .proposal_views import _current_assignments

SHOWN = 10


def _latest_version():
    return Subquery(ProposalVersion.objects.filter(
        proposal=OuterRef('proposal')).order_by('-number').values('pk')[:1])


def awaiting_pairs(office_ids):
    """(proposal, office) pairs in concurrence where that office has not
    yet concurred on the current version. One query."""
    return ProposalParticipant.objects.filter(
        role=ProposalParticipant.CONCURRING, office_id__in=list(office_ids),
        proposal__status=Proposal.CONCURRENCE,
    ).annotate(latest_version=_latest_version()).exclude(Exists(
        Concurrence.objects.filter(version=OuterRef('latest_version'),
                                   office=OuterRef('office'), decision=Concurrence.CONCUR)
    ))


def awaiting_count(office_ids):
    """Proposals waiting on any of these offices. One aggregate query."""
    if not office_ids:
        return 0
    return awaiting_pairs(office_ids).values('proposal').distinct().count()


def _row(proposal, kind, label, severity, office=None):
    return {
        'kind': kind, 'label': label, 'severity': severity,
        'proposal_id': proposal.pk, 'manual': proposal.manual.title,
        'manual_id': proposal.manual_id, 'dcr_number': proposal.dcr_number,
        'office': office or proposal.initiating_office.name,
        'since': proposal.updated_at,
    }


def _section(key, title, total, rows):
    return {'key': key, 'title': title, 'total': total, 'items': rows} if total else None


def staff_sections(user):
    posts = _current_assignments(user)
    office_ids = {a.position.office_id for a in posts}
    head_of = {a.position.office_id for a in posts if a.position.kind == Position.HEAD}
    if not office_ids:
        return []

    pairs = awaiting_pairs(office_ids)
    waiting = list(pairs.select_related(
        'proposal', 'proposal__manual', 'proposal__initiating_office', 'office',
    ).order_by('proposal__updated_at')[:SHOWN])
    concur = _section(
        'concurrence', 'Waiting for your office to concur',
        pairs.values('proposal').distinct().count(),
        [_row(p.proposal, 'concurrence',
              'Concur or return' if p.office_id in head_of else 'Waiting on your Head',
              'action' if p.office_id in head_of else 'info', office=p.office.name)
         for p in waiting],
    )

    mine = Proposal.objects.filter(initiating_office_id__in=office_ids).select_related(
        'manual', 'initiating_office')
    # Drafting again after a return: a draft whose version is not the first.
    returned = mine.filter(status=Proposal.DRAFT).filter(
        Exists(ProposalVersion.objects.filter(proposal=OuterRef('pk'), number__gt=1)))
    redraft = _section(
        'returned', 'Returned to your office', returned.count(),
        [_row(p, 'returned', 'Redraft', 'action') for p in returned.order_by('updated_at')[:SHOWN]],
    )
    signing = mine.filter(status__in=(Proposal.LOCKED, Proposal.AWAITING_SIGNATURE,
                                      Proposal.PACKAGE_RETURNED))
    sign = _section(
        'signing', 'Signed copies to upload', signing.count(),
        [_row(p, 'signing',
              'Fix the returned copies' if p.status == Proposal.PACKAGE_RETURNED
              else 'Upload signed copies', 'action')
         for p in signing.order_by('updated_at')[:SHOWN]],
    )
    return [s for s in (concur, redraft, sign) if s]


def qms_sections(user):
    kinds = {a.position.kind for a in _current_assignments(
        user, [Position.IMR, Position.DOCUMENT_CUSTODIAN])}
    base = Proposal.objects.select_related('manual', 'initiating_office')
    sections = []
    if Position.IMR in kinds:
        for status, key, title, label in (
                (Proposal.READY_FOR_IMR, 'imr', 'Ready for your decision', 'Accept or deny'),
                (Proposal.AWAITING_APPROVAL, 'approval', 'Awaiting the signed DCR',
                 'Upload the signed DCR')):
            rows = base.filter(status=status)
            sections.append(_section(key, title, rows.count(),
                                     [_row(p, key, label, 'action')
                                      for p in rows.order_by('updated_at')[:SHOWN]]))
    if Position.DOCUMENT_CUSTODIAN in kinds:
        rows = base.filter(status=Proposal.WITH_CUSTODIAN)
        sections.append(_section('custodian', 'With you to accept', rows.count(),
                                 [_row(p, 'custodian', 'Accept or return', 'action')
                                  for p in rows.order_by('updated_at')[:SHOWN]]))
    return [s for s in sections if s]


def admin_sections():
    today_holders = PositionAssignment.objects.filter(
        user=OuterRef('pk'), ends_on__isnull=True)
    pending = CustomUser.objects.filter(is_approved=False).count()
    unplaced = CustomUser.objects.filter(
        is_approved=True, is_active=True, system_role=CustomUser.USER,
    ).exclude(Exists(today_holders)).count()
    vacant = len(monitoring.find_vacancies())
    counts = [
        ('pending', 'Sign-ups to approve', pending, 'people'),
        ('unplaced', 'Approved but holding no post', unplaced, 'people'),
        ('vacant', 'Posts with no holder', vacant, 'people'),
    ]
    return [{'key': key, 'title': title, 'total': n, 'items': [], 'go': page}
            for key, title, n, page in counts if n]


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def needs_action(request):
    """Every section that has something in it, for whichever roles this
    person holds. Empty sections are left out, not sent as zero."""
    user = request.user
    sections = []
    if user.system_role == CustomUser.SYSTEM_ADMIN:
        sections += admin_sections()
    sections += qms_sections(user)
    if access.current_offices(user):
        sections += staff_sections(user)
    return Response({
        'total': sum(s['total'] for s in sections),
        'sections': sections,
    })
