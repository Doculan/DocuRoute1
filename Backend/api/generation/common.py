"""What the three generators share.

Every generated file goes out through `save`, and `save` scrubs the
document's personal properties first. `python-docx` copies a template's
properties into everything made from it, so without this a template
committed with its author still in it would print that name - invisibly,
in the file's properties - on every DCR the system produced.
"""

import copy
import io
import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from ..document_hygiene import scrub_document
from ..models import Attachment, Position

DOCX_TYPE = ('application/vnd.openxmlformats-officedocument'
             '.wordprocessingml.document')

# Beside MEDIA_ROOT, not under it: tests point MEDIA_ROOT at a temporary
# folder, and the templates must still be found.
TEMPLATE_DIR = os.path.join(settings.BASE_DIR, 'media')
DCR_TEMPLATE = os.path.join(
    TEMPLATE_DIR, 'templates',
    'F-QMS-001-Document-Change-Request-Rev.1-01-05-26.docx',
)
PAGES_TEMPLATE = os.path.join(
    TEMPLATE_DIR, 'MANUAL_BLANK_FORMAT', 'MANUAL_BLANK.docx',
)

_KIND_LABEL = dict(Position.KIND_CHOICES)


class TemplateChanged(RuntimeError):
    """The template no longer has the shape the generator was written for.

    Raised rather than guessed around: generation runs inside the lock, so
    this fails the lock loudly instead of printing a misfilled form.
    """


def position_title(office_name, kind):
    """"Accounting Office — Encoder". Never a person's name."""
    return f"{office_name} — {_KIND_LABEL[kind]}"


def form_date(moment):
    """The date as the university's forms write it: "September 23, 2026"."""
    day = timezone.localtime(moment).date()
    return f"{day:%B} {day.day}, {day.year}"


def changed_sections(version):
    """This version's changed sections, in document order."""
    changes = version.changes.select_related('section').order_by('section__order')
    return [c for c in changes if c.has_changed]


def save(document, proposal, version, kind, actor, filename, slot='', section=None):
    """Scrub, serialise, check and record one generated document."""
    scrub_document(document)
    buffer = io.BytesIO()
    document.save(buffer)
    data = buffer.getvalue()
    check_package(data, filename)

    attachment = Attachment(
        proposal=proposal, version=version, kind=kind, slot=slot,
        section=section, created_by=actor, original_filename=filename,
        content_type=DOCX_TYPE, size_bytes=len(data),
    )
    attachment.file.save(filename, ContentFile(data), save=False)
    attachment.save()
    return attachment


def check_package(data, filename):
    """Refuse a generated file that is malformed or still carries a name.

    Checked on the bytes that will be stored, not on the object that made
    them. The DCR template once declared its properties part under a
    relationship type `python-docx` did not recognise, so scrubbing
    created a second `docProps/core.xml` beside the first: the file held
    two sets of properties, and which one a reader believed was up to the
    reader. Scrubbing the object said nothing about that. Reading the
    result does.

    Raises inside the lock, so the lock fails rather than storing it.
    """
    import collections
    import zipfile

    from ..document_hygiene import docx_personal_metadata

    with zipfile.ZipFile(io.BytesIO(data)) as package:
        repeated = [name for name, count in
                    collections.Counter(package.namelist()).items() if count > 1]
    if repeated:
        raise TemplateChanged(
            f'{filename}: the generated file repeats {", ".join(sorted(repeated))}'
        )
    personal = docx_personal_metadata(io.BytesIO(data))
    if personal:
        raise TemplateChanged(
            f'{filename}: the generated file still carries {", ".join(sorted(personal))}'
        )


# --- small XML helpers ---------------------------------------
#
# Word checks the order of the children of `w:pPr` and `w:rPr` against the
# schema, and a file with them out of order can open as "unreadable
# content". So nothing is appended blindly: every property is inserted at
# its place in these sequences (ECMA-376, CT_PPrBase and CT_RPr).

_PPR_ORDER = [
    'pStyle', 'keepNext', 'keepLines', 'pageBreakBefore', 'framePr',
    'widowControl', 'numPr', 'suppressLineNumbers', 'pBdr', 'shd', 'tabs',
    'suppressAutoHyphens', 'kinsoku', 'wordWrap', 'overflowPunct',
    'topLinePunct', 'autoSpaceDE', 'autoSpaceDN', 'bidi', 'adjustRightInd',
    'snapToGrid', 'spacing', 'ind', 'contextualSpacing', 'mirrorIndents',
    'suppressOverlap', 'jc', 'textDirection', 'textAlignment',
    'textboxTightWrap', 'outlineLvl', 'divId', 'cnfStyle', 'rPr', 'sectPr',
    'pPrChange',
]
_RPR_ORDER = [
    'rStyle', 'rFonts', 'b', 'bCs', 'i', 'iCs', 'caps', 'smallCaps',
    'strike', 'dstrike', 'outline', 'shadow', 'emboss', 'imprint', 'noProof',
    'snapToGrid', 'vanish', 'webHidden', 'color', 'spacing', 'w', 'kern',
    'position', 'sz', 'szCs', 'highlight', 'u', 'effect', 'bdr', 'shd',
    'fitText', 'vertAlign', 'rtl', 'cs', 'em', 'lang', 'eastAsianLayout',
    'specVanish', 'oMath',
]

_TBLPR_ORDER = [
    'tblStyle', 'tblpPr', 'tblOverlap', 'bidiVisual', 'tblStyleRowBandSize',
    'tblStyleColBandSize', 'tblW', 'jc', 'tblCellSpacing', 'tblInd',
    'tblBorders', 'shd', 'tblLayout', 'tblCellMar', 'tblLook', 'tblCaption',
    'tblDescription',
]


def _local(element):
    return element.tag.split('}')[-1]


def put(parent, element, order):
    """Insert `element` into `parent` at its schema position.

    Replaces an existing child of the same name, so calling twice sets
    rather than duplicates.
    """
    name = _local(element)
    for child in list(parent):
        if _local(child) == name and child.tag == element.tag:
            parent.remove(child)
    rank = order.index(name)
    for child in parent:
        other = _local(child)
        if other in order and order.index(other) > rank:
            child.addprevious(element)
            return element
    parent.append(element)
    return element


def _properties(element, tag):
    props = element.find(qn(tag))
    if props is None:
        props = OxmlElement(tag)
        element.insert(0, props)
    return props


def _element(tag, **attrs):
    element = OxmlElement(tag)
    for key, value in attrs.items():
        element.set(qn(key), value)
    return element


def remove_property(parent, tag):
    old = parent.find(qn(tag))
    if old is not None:
        parent.remove(old)


def set_run_font(run_element, size=None, bold=None, underline=None, font='Arial'):
    """Set font, size and emphasis on a `w:r`, creating `w:rPr` if needed."""
    rPr = _properties(run_element, 'w:rPr')
    if font:
        put(rPr, _element('w:rFonts', **{'w:ascii': font, 'w:hAnsi': font, 'w:cs': font}), _RPR_ORDER)
    if bold is not None:
        remove_property(rPr, 'w:b')
        remove_property(rPr, 'w:bCs')
        if bold:
            put(rPr, _element('w:b'), _RPR_ORDER)
            put(rPr, _element('w:bCs'), _RPR_ORDER)
    if underline is not None:
        remove_property(rPr, 'w:u')
        if underline:
            put(rPr, _element('w:u', **{'w:val': 'single'}), _RPR_ORDER)
    if size is not None:
        half_points = str(int(round(size * 2)))
        put(rPr, _element('w:sz', **{'w:val': half_points}), _RPR_ORDER)
        put(rPr, _element('w:szCs', **{'w:val': half_points}), _RPR_ORDER)
    return rPr


def new_run(text, size, bold=False, underline=False):
    """A `w:r` holding `text`, tabs and all."""
    run = OxmlElement('w:r')
    set_run_font(run, size=size, bold=bold, underline=underline)
    set_run_text(run, text)
    return run


def set_run_text(run_element, text):
    """Replace a run's text, keeping its formatting. Tabs become `w:tab`."""
    for child in list(run_element):
        if child.tag in (qn('w:t'), qn('w:tab'), qn('w:br')):
            run_element.remove(child)
    for i, piece in enumerate(text.split('\t')):
        if i:
            run_element.append(OxmlElement('w:tab'))
        if piece:
            t = OxmlElement('w:t')
            t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
            t.text = piece
            run_element.append(t)


def set_spacing(paragraph_element, line_pt=None, before_pt=0.0, after_pt=0.0):
    """Exact line spacing and explicit before/after, in points.

    Twentieths of a point, rounded down for `after` - the spacer beneath a
    block must never come out a hair taller than the room it was given.
    """
    pPr = _properties(paragraph_element, 'w:pPr')
    attrs = {
        'w:before': str(int(round(before_pt * 20))),
        'w:after': str(max(0, int(after_pt * 20))),
    }
    if line_pt is not None:
        attrs['w:line'] = str(int(round(line_pt * 20)))
        attrs['w:lineRule'] = 'exact'
    return put(pPr, _element('w:spacing', **attrs), _PPR_ORDER)


def set_indent(paragraph_element, start_twips=0, end_twips=0):
    pPr = _properties(paragraph_element, 'w:pPr')
    return put(pPr, _element('w:ind', **{'w:start': str(start_twips), 'w:end': str(end_twips)}), _PPR_ORDER)


def set_alignment(paragraph_element, value):
    pPr = _properties(paragraph_element, 'w:pPr')
    return put(pPr, _element('w:jc', **{'w:val': value}), _PPR_ORDER)


def set_mark_size(paragraph_element, size):
    """The paragraph mark's size. An empty paragraph is exactly this tall."""
    pPr = _properties(paragraph_element, 'w:pPr')
    mark = pPr.find(qn('w:rPr'))
    if mark is None:
        mark = put(pPr, OxmlElement('w:rPr'), _PPR_ORDER)
    half_points = str(int(round(size * 2)))
    put(mark, _element('w:sz', **{'w:val': half_points}), _RPR_ORDER)
    put(mark, _element('w:szCs', **{'w:val': half_points}), _RPR_ORDER)


def clone(element):
    return copy.deepcopy(element)
