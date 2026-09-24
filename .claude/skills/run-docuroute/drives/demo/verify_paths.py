"""After `paths.sh`, confirm in the database what the screens showed.

Run inside `manage.py shell --settings=scratch_settings -c "exec(open(...).read())"`
on the same scratch copy. Prints one block per path and a final verdict.
"""
from django.conf import settings
assert 'scratch' in settings.SETTINGS_MODULE, 'run with --settings=scratch_settings'
from api.models import (
    Attachment, Concurrence, DocumentStatus, Manual, Proposal, SectionChange, SectionHistory,
)

problems = []


def check(label, ok):
    print(('  ok    ' if ok else '  WRONG ') + label)
    if not ok:
        problems.append(label)


def requests(title):
    return list(Proposal.objects.filter(manual__title=title).order_by('created_at'))


def events(p):
    return [e.event for e in p.events.order_by('at')]


def holds(p):
    return SectionChange.objects.filter(version__proposal=p, is_open=True).count()


print('== effective (FAM 6.02)')
[p] = requests('FAM 6.02')
manual = Manual.objects.get(title='FAM 6.02')
section = manual.sections.get(subtitle='2.0 SCOPE')
check('the request is effective', p.status == Proposal.EFFECTIVE)
check('the section text changed', 'LNU Dormitory' in section.content)
row = SectionHistory.objects.filter(section=section, proposal=p).first()
check('its history row links the DCR', row is not None and row.source == 'proposal')
statuses = list(DocumentStatus.objects.filter(manual=manual).order_by('recorded_at'))
check('baseline 1, its correction 2, then the change 3',
      [s.revision for s in statuses] == ['1', '2', '3'])
check('the mistaken baseline is kept, superseded by the correction',
      statuses[0].superseded_by_id == statuses[1].id and statuses[1].correction_reason != '')
check('the document shows revision 3', manual.current_status_id == statuses[2].id)
check('no holds left', holds(p) == 0)

print('== return, redraft, resubmit (FAM 6.03)')
[p] = requests('FAM 6.03')
v1, v2 = p.versions.order_by('number')
check('locked on version 2', p.status == Proposal.AWAITING_SIGNATURE and p.current_version() == v2)
check('version 1: Cash concurred, Budget returned',
      sorted(Concurrence.objects.filter(version=v1).values_list('decision', flat=True))
      == ['concur', 'return'])
check('version 2: both concurred again - the reset',
      list(Concurrence.objects.filter(version=v2).values_list('decision', flat=True))
      == ['concur', 'concur'])
change = v2.changes.get()
check('version 2 carries the redrafted text, checked', 'timely submission' in change.new_text
      and change.check_is_current)
check('events: returned, redrafted, submitted again',
      events(p).count('submitted') == 2 and 'returned' in events(p))

print('== withdrawal (FAM 6.01)')
first, again = requests('FAM 6.01')
check('the first request is withdrawn, with its reason',
      first.status == Proposal.WITHDRAWN and first.withdrawn_reason != '')
check('it holds nothing', holds(first) == 0)
check('the same section was drafted again', again.status == Proposal.DRAFT and holds(again) == 1)

print('== IMR denial (FAM 5.01)')
first, again = requests('FAM 5.01')
denial = first.qms_decisions.get()
check('denied, with the reason', first.status == Proposal.DENIED and denial.outcome == 'deny'
      and 'Board' in denial.comments)
check('it holds nothing', holds(first) == 0)
check('the same section was drafted again', again.status == Proposal.DRAFT and holds(again) == 1)
check('the text is unchanged', 'five working days' not in
      Manual.objects.get(title='FAM 5.01').sections.get(subtitle='1.0 OBJECTIVES').content)

print('== custodian return (FAM 4.02)')
[p] = requests('FAM 4.02')
outcomes = list(p.qms_decisions.order_by('decided_at').values_list('outcome', flat=True))
check('accepted, returned, then made effective', outcomes == ['accept', 'return', 'effective'])
dcr = Attachment.objects.filter(proposal=p, kind=Attachment.SIGNED_DCR).order_by('created_at')
check('the named copy replaced, the first kept as superseded',
      dcr.count() == 2 and dcr[0].superseded_at is not None and dcr[1].superseded_at is None)
check('only the named copy was replaced',
      Attachment.objects.filter(proposal=p, kind=Attachment.SIGNED_PAGES).count() == 1)
check('the text changed', 'reviewed each year' in
      Manual.objects.get(title='FAM 4.02').sections.get(subtitle='1.0 OBJECTIVES').content)

print('== open drafts per office and document: at most one')
from django.db.models import Count
dup = (Proposal.objects.filter(status__in=Proposal.OPEN_STATUSES)
       .values('manual', 'initiating_office').annotate(n=Count('id')).filter(n__gt=1))
check('no second draft from a double start', not dup.exists())

print('ALL PATHS CONFIRMED' if not problems else f'{len(problems)} WRONG: {problems}')
