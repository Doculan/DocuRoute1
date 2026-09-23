"""The pre-filled Document Change Request, F-QMS-001.

Filled from the official form, never redrawn: the template is the
university's controlled document, and what the system adds is text in its
blanks.

**Position titles, never names.** "Requested by" and "Department/Unit Head"
carry the positions; the people write their own names when they sign.

**One page, always.** Every row of the form grows with its content, so an
over-long reason would push sections 3 to 5 onto a second sheet. Section 2
is therefore measured before it is written (see `metrics`): the list of
changed sections shrinks, then abbreviates; the reason shrinks, and if it
still cannot fit it is stated in full in the annex instead.

**Two copies of each signature label.** The labels are floating text boxes,
and each exists twice - DrawingML for current Word, VML for older readers.
Both are written identically. A copy left stale shows the wrong thing in
whichever application reads it.

Left blank for hand-filling, as the manual header is: Document Title and
Revision Status. The system holds the document's number but not its name,
and the revision is only known reliably from the paper record.
"""

import math
import re

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from ..models import Attachment, Position
from . import metrics
from .common import (
    DCR_TEMPLATE, TemplateChanged, changed_sections, clone, form_date,
    new_run, position_title, remove_property, save, set_alignment, set_indent,
    set_mark_size, set_run_font, set_run_text, set_spacing,
)

WP = '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
WPS = '{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
VML = '{urn:schemas-microsoft-com:vml}'
W10 = '{urn:schemas-microsoft-com:office:word}'
MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
EMU = 12700                  # per point

# Where section text starts within the cell: the headings' own tab stop.
BODY_INDENT_TWIPS = 540

FIELD_SIZES = (11, 10.5, 10, 9.5, 9)
CHANGES_SIZES = (10, 9.5, 9, 8.5, 8)
REASON_SIZES = (10, 9.5, 9, 8.5, 8, 7.5, 7)
TITLE_ONE_LINE = (9, 8.5, 8)
TITLE_TWO_LINES = (9, 8.5, 8, 7.5, 7)

# The signature boxes are widened to this and centred on their lines, so
# a long office name has room without crowding the other signatory.
LABEL_BOX_WIDTH = 190.0

REASON_IN_ANNEX = 'Stated in full in the annex to this request.'
SEE_DRAFT = 'See attached draft copy.'


# --- planning: what goes where, before anything is written ---

def requester_title(proposal):
    """The drafter's position in the initiating office, else its Encoder."""
    from ..proposal_views import _held_position

    office = proposal.initiating_office
    held = _held_position(proposal.created_by, office,
                          kinds=[Position.ENCODER, Position.HEAD])
    kind = held.kind if held is not None else Position.ENCODER
    return position_title(office.name, kind)


def head_title(proposal):
    return position_title(proposal.initiating_office.name, Position.HEAD)


def plan(proposal, version):
    """Everything the DCR will say and at what size, decided in one place.

    The annex generator calls this too, to know whether the reason moved
    there - so the two cannot disagree about it.
    """
    document = Document(DCR_TEMPLATE)
    form = _Form(document)
    changes = changed_sections(version)

    titles = {
        'Requested by': requester_title(proposal),
        'Department/Unit Head': head_title(proposal),
    }
    boxes = {label: form.fit_title(label, text) for label, text in titles.items()}

    changes_plan = _fit_changes(
        [c.section.subtitle.strip() for c in changes],
        form.body_width, form.area_height(form.changes_area),
    )

    reason_room = form.reason_room(boxes)
    reason_lines = [line.rstrip() for line in version.overall_reason.splitlines()
                    if line.strip()]
    fitted = metrics.fit(reason_lines, form.body_width, reason_room, REASON_SIZES)
    if fitted is None:
        reason_plan = {'paragraphs': [REASON_IN_ANNEX], 'size': 10, 'in_annex': True}
    else:
        reason_plan = {'paragraphs': reason_lines, 'size': fitted[0], 'in_annex': False}

    return {
        'document': document, 'form': form, 'titles': titles, 'boxes': boxes,
        'changes': changes_plan, 'reason': reason_plan,
        'reason_in_annex': reason_plan['in_annex'],
    }


def _fit_changes(names, width, height):
    """The changed sections, then "see attached", at the largest size that fits.

    A summary, so it may abbreviate: if every name cannot fit even at the
    smallest size, the list is cut and says how many it left out. The
    draft copy it points to lists them all.
    """
    def paragraphs(shown):
        listed = '; '.join(names[:shown])
        rest = len(names) - shown
        if rest:
            listed += '; and %d other section%s' % (rest, '' if rest == 1 else 's')
        return ['Sections amended: ' + listed + '.', SEE_DRAFT]

    for shown in range(len(names), 0, -1):
        fitted = metrics.fit(paragraphs(shown), width, height, CHANGES_SIZES)
        if fitted is not None:
            return {'paragraphs': paragraphs(shown), 'size': fitted[0]}
    # Not even one name fits: the pointer to the draft still does.
    return {'paragraphs': [SEE_DRAFT], 'size': CHANGES_SIZES[-1]}


# --- generation ----------------------------------------------

def generate(proposal, version, actor):
    layout = plan(proposal, version)
    document, form = layout['document'], layout['form']

    form.fill_header(
        date=form_date(proposal.locked_at),
        dcr_number=proposal.dcr_number,
        office=proposal.initiating_office.name,
    )
    form.tick('Amend document')
    form.fill_field('Document Number', proposal.manual.title)

    form.fill_area(form.changes_area, layout['changes']['paragraphs'],
                   layout['changes']['size'])
    form.fill_area(form.reason_area, layout['reason']['paragraphs'],
                   layout['reason']['size'])
    for label, fitted in layout['boxes'].items():
        form.write_title(label, fitted)

    return [save(
        document, proposal, version, Attachment.DCR_GENERATED, actor,
        filename=f'{proposal.dcr_number} Document Change Request.docx',
    )]


# --- the form ------------------------------------------------

def _text(paragraph_element):
    parts = []
    for node in paragraph_element.iter(qn('w:t'), qn('w:tab')):
        # A tab stop's definition shares the tag of a typed tab; only the
        # typed ones, inside runs, are text.
        if node.tag == qn('w:tab') and node.getparent().tag != qn('w:r'):
            continue
        # Text inside text boxes belongs to the box, not the paragraph.
        if any(a.tag == qn('w:txbxContent') for a in node.iterancestors()):
            continue
        parts.append('\t' if node.tag == qn('w:tab') else (node.text or ''))
    return ''.join(parts)


def _run_text(run_element):
    return ''.join('\t' if n.tag == qn('w:tab') else (n.text or '')
                   for n in run_element if n.tag in (qn('w:t'), qn('w:tab')))


def _has_drawing(element):
    return (element.find('.//' + qn('w:drawing')) is not None
            or element.find('.//' + qn('w:pict')) is not None)


def _pt(emu):
    return int(emu) / EMU


class _Form:
    """The DCR template, located by its printed labels."""

    def __init__(self, document):
        self.document = document
        tables = document.tables
        if len(tables) != 1:
            raise TemplateChanged('expected the DCR as a single table')
        self.table = tables[0]

        tbl = self.table._tbl
        width = tbl.find(qn('w:tblPr')).find(qn('w:tblW'))
        margins = tbl.find(qn('w:tblPr')).find(qn('w:tblCellMar'))
        side = sum(int(m.get(qn('w:w'))) for m in margins
                   if m.tag in (qn('w:start'), qn('w:end'), qn('w:left'), qn('w:right')))
        self.cell_width = (int(width.get(qn('w:w'))) - side) / 20.0
        self.body_width = self.cell_width - BODY_INDENT_TWIPS / 20.0
        self.default_tab = self._default_tab()
        self.normal_size = document.styles['Normal'].font.size.pt

        self.section2 = self._cell_containing('CHANGE(S) REQUESTED')
        paragraphs = list(self.section2._tc.iter(qn('w:p')))
        # Only the cell's own paragraphs, not those inside its text boxes.
        paragraphs = [p for p in paragraphs if p.getparent() is self.section2._tc]
        heads = [i for i, p in enumerate(paragraphs) if 'CHANGE(S) REQUESTED' in _text(p)]
        reasons = [i for i, p in enumerate(paragraphs) if 'REASON FOR THE CHANGE' in _text(p)]
        if not heads or not reasons:
            raise TemplateChanged('section 2 headings not found')
        first_sig = next((i for i in range(reasons[0] + 1, len(paragraphs))
                          if _has_drawing(paragraphs[i])), None)
        if first_sig is None:
            raise TemplateChanged('section 2 signature lines not found')

        self.changes_area = paragraphs[heads[0] + 1:reasons[0]]
        self.reason_area = paragraphs[reasons[0] + 1:first_sig]
        for p in self.changes_area + self.reason_area:
            if _text(p).strip() or _has_drawing(p):
                raise TemplateChanged('section 2 writing space is not empty')
        self.signature_paragraphs = paragraphs[first_sig:first_sig + 2]
        self.boxes = self._label_boxes()

    # locating

    def _default_tab(self):
        settings = self.document.settings.element
        stop = settings.find(qn('w:defaultTabStop'))
        return int(stop.get(qn('w:val'))) / 20.0 if stop is not None else 36.0

    def _cell_containing(self, needle):
        for row in self.table.rows:
            for cell in row.cells:
                if needle in cell.text:
                    return cell
        raise TemplateChanged(f'{needle!r} not found on the form')

    def _paragraph_containing(self, needle):
        for p in self.table._tbl.iter(qn('w:p')):
            if needle in _text(p):
                return p
        raise TemplateChanged(f'{needle!r} not found on the form')

    # measuring

    def _mark_size(self, paragraph):
        size = paragraph.find('./' + qn('w:pPr') + '/' + qn('w:rPr') + '/' + qn('w:sz'))
        return int(size.get(qn('w:val'))) / 2.0 if size is not None else self.normal_size

    def _single_line(self, paragraph):
        """How tall an empty template paragraph is, at single spacing."""
        return metrics.LINE_FACTOR * self._mark_size(paragraph)

    def area_height(self, paragraphs):
        return sum(self._single_line(p) for p in paragraphs)

    def _tab_stops(self, paragraph):
        stops = []
        tabs = paragraph.find('./' + qn('w:pPr') + '/' + qn('w:tabs'))
        if tabs is not None:
            for tab in tabs:
                if tab.get(qn('w:val')) != 'clear':
                    stops.append(int(tab.get(qn('w:pos'))) / 20.0)
        return sorted(stops)

    def _x_after(self, paragraph, text, size):
        """Where the pen ends after `text`, honouring the paragraph's tabs."""
        stops = self._tab_stops(paragraph)
        x = 0.0
        for ch in text:
            if ch == '\t':
                later = [s for s in stops if s > x + 0.01]
                x = later[0] if later else (math.floor(x / self.default_tab) + 1) * self.default_tab
            else:
                x += metrics.text_width(ch, size)
        return x

    def _rule_end(self, paragraph):
        """The right end of the drawn rule a field is written on."""
        for anchor in paragraph.iter(WP + 'anchor'):
            h = anchor.find(WP + 'positionH')
            if h.get('relativeFrom') != 'column':
                continue
            start = _pt(h.findtext(WP + 'posOffset'))
            return start + _pt(anchor.find(WP + 'extent').get('cx'))
        return None

    def _field_size(self, text, start, rule_end):
        """Fit the rule if possible; otherwise stay on one line in the cell."""
        if rule_end is not None:
            size = metrics.fit_one_line(text, rule_end - start, FIELD_SIZES)
            if size is not None:
                return size
        size = metrics.fit_one_line(
            text, self.cell_width - start, FIELD_SIZES[-1:] + (8.5, 8, 7.5, 7, 6.5, 6),
        )
        return size or 6

    # the single-line fields

    def fill_header(self, date, dcr_number, office):
        paragraph = self._paragraph_containing('DCR No.')
        run = next((r for r in paragraph.findall(qn('w:r')) if 'DCR No.' in _run_text(r)), None)
        match = re.match(r'^(DATE\t:\t)( +)(DCR No\.\s*)(_+)\s*$', _run_text(run) if run is not None else '')
        if match is None:
            raise TemplateChanged('the DATE / DCR No. line has changed')
        label, spaces, dcr_label, _underscores = match.groups()

        # Take the date's width back out of the spaces, so "DCR No." stays
        # where the form put it and the line cannot wrap.
        space = metrics.text_width(' ', 11)
        keep = max(1, len(spaces) - math.ceil(metrics.text_width(date, 11) / space))
        set_run_text(run, label + date + ' ' * keep + dcr_label)
        run.addnext(new_run(dcr_number, 11, underline=True))

        paragraph = self._paragraph_containing('FROM')
        runs = paragraph.findall(qn('w:r'))
        label_run = next((r for r in runs if _run_text(r).startswith('FROM')), None)
        if label_run is None:
            raise TemplateChanged('the FROM line has changed')
        for later in runs[runs.index(label_run) + 1:]:
            if not _has_drawing(later) and not _run_text(later).strip():
                paragraph.remove(later)
        start = self._x_after(paragraph, 'FROM\t:\t', 11)
        size = self._field_size(office, start, self._rule_end(paragraph))
        label_run.addnext(new_run('\t' + office, size))

    def fill_field(self, label, value):
        paragraph = self._paragraph_containing(label)
        runs = [r for r in paragraph.findall(qn('w:r')) if not _has_drawing(r)]
        prefix = ''.join(_run_text(r) for r in runs)
        if not prefix.rstrip(' ').endswith(':\t'):
            raise TemplateChanged(f'the {label} line has changed')
        start = self._x_after(paragraph, prefix, 11)
        size = self._field_size(value, start, self._rule_end(paragraph))
        runs[-1].addnext(new_run(value, size))

    def tick(self, label):
        paragraph = self._paragraph_containing(label)
        runs = paragraph.findall(qn('w:r'))
        for i, run in enumerate(runs[:-1]):
            if _run_text(run).endswith('[') and not _run_text(runs[i + 1]).strip():
                mark = runs[i + 1]
                set_run_text(mark, ' X ')
                # The blank carries the template's red and a smaller size;
                # the mark is an answer on the form, so it takes the
                # brackets' size and prints black.
                size = run.find('./' + qn('w:rPr') + '/' + qn('w:sz'))
                size = int(size.get(qn('w:val'))) / 2.0 if size is not None else None
                rPr = set_run_font(mark, bold=True, size=size, font=None)
                remove_property(rPr, 'w:color')
                return
        raise TemplateChanged(f'the {label} box has changed')

    # section 2

    def fill_area(self, area, paragraphs, size):
        """Replace empty template lines with text of exactly the same height.

        Explicit line breaks at the measured wrap points, and exact line
        spacing, so the height Word lays out is the height computed here.
        The last paragraph's spacing takes up whatever is left, so nothing
        below moves.
        """
        budget = self.area_height(area)
        line = metrics.line_height(size)
        used = 0.0
        made = []
        for text in paragraphs:
            lines = metrics.wrap(text, self.body_width, size)
            p = OxmlElement('w:p')
            set_spacing(p, line_pt=line)
            set_indent(p, BODY_INDENT_TWIPS, 0)
            set_mark_size(p, size)
            run = new_run('', size)
            for i, piece in enumerate(lines):
                if i:
                    run.append(OxmlElement('w:br'))
                t = OxmlElement('w:t')
                t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                t.text = piece
                run.append(t)
            p.append(run)
            made.append(p)
            used += len(lines) * line
        if used > budget + 0.01:
            raise ValueError('planned text does not fit its area')

        set_spacing(made[-1], line_pt=line, after_pt=budget - used)
        for p in made:
            area[0].addprevious(p)
        for p in area:
            p.getparent().remove(p)

    def _label_boxes(self):
        """Each signature label, both of its copies, and the rule above it."""
        heights = [self._single_line(p) for p in self.signature_paragraphs]
        # Everything in the coordinates of the second signature paragraph,
        # which is where this form anchors its rules.
        shifts = [-heights[0], 0.0]
        rules = []
        for index, p in enumerate(self.signature_paragraphs):
            for anchor in p.iter(WP + 'anchor'):
                geometry = anchor.find('.//' + A + 'prstGeom')
                if geometry is not None and geometry.get('prst') == 'straightConnector1':
                    h = _pt(anchor.find(WP + 'positionH').findtext(WP + 'posOffset'))
                    width = _pt(anchor.find(WP + 'extent').get('cx'))
                    top = _pt(anchor.find(WP + 'positionV').findtext(WP + 'posOffset'))
                    rules.append({'centre': h + width / 2, 'y': top + shifts[index]})

        boxes = {}
        for index, p in enumerate(self.signature_paragraphs):
            for alternate in p.iter(MC + 'AlternateContent'):
                choice = alternate.find(MC + 'Choice')
                fallback = alternate.find(MC + 'Fallback')
                if choice is None or fallback is None:
                    continue
                modern = choice.find('.//' + qn('w:txbxContent'))
                legacy = fallback.find('.//' + qn('w:txbxContent'))
                if modern is None or legacy is None:
                    continue
                label = _text_of_box(modern)
                if label not in ('Requested by', 'Department/Unit Head'):
                    continue
                if _text_of_box(legacy) != label:
                    raise TemplateChanged(f'the two copies of {label!r} differ')
                anchor = choice.find('.//' + WP + 'anchor')
                shape = legacy.getparent().getparent()   # v:textbox -> v:shape/v:rect
                body = choice.find('.//' + WPS + 'bodyPr')
                top = _pt(anchor.find(WP + 'positionV').findtext(WP + 'posOffset'))
                h = _pt(anchor.find(WP + 'positionH').findtext(WP + 'posOffset'))
                width = _pt(anchor.find(WP + 'extent').get('cx'))
                centre = h + width / 2
                rule = min(rules, key=lambda r: abs(r['centre'] - centre))
                boxes[label] = {
                    'anchor': anchor, 'shape': shape,
                    'copies': (modern, legacy),
                    'top': top, 'top_in_rule_space': top + shifts[index],
                    'height': _pt(anchor.find(WP + 'extent').get('cy')),
                    'inset_top': _pt(body.get('tIns', 45720)),
                    'inset_side': _pt(body.get('lIns', 91440)) + _pt(body.get('rIns', 91440)),
                    'rule': rule,
                }
        if set(boxes) != {'Requested by', 'Department/Unit Head'}:
            raise TemplateChanged('the section 2 signature labels were not both found')
        self._first_sig_height = heights[0]
        return boxes

    def fit_title(self, label, title):
        """Size and line breaks for one position title, and the room it takes."""
        box = self.boxes[label]
        inner = LABEL_BOX_WIDTH - box['inset_side']
        size = metrics.fit_one_line(title, inner, TITLE_ONE_LINE, bold=True)
        if size is not None:
            lines = [title]
        else:
            for size in TITLE_TWO_LINES:
                lines = metrics.wrap(title, inner, size, bold=True)
                if len(lines) <= 2:
                    break
            else:
                size = TITLE_TWO_LINES[-1]
                lines = metrics.wrap(title, inner, size, bold=True)
        height = len(lines) * metrics.line_height(size)
        # The gap that keeps the label exactly where the form printed it:
        # the title's last line ends on the rule, the label starts below.
        gap = box['top_in_rule_space'] + box['inset_top'] - box['rule']['y']
        return {'size': size, 'lines': lines, 'height': height, 'gap': gap}

    def reason_room(self, fitted_titles):
        """How tall the reason may be without meeting a title from below.

        The titles now rise above the signature rules, into space the form
        left empty. The reason is kept at least a point clear of the
        highest one, and never taller than its own empty lines.
        """
        area = self.area_height(self.reason_area)
        tops = []
        for label, fitted in fitted_titles.items():
            box = self.boxes[label]
            raised = box['top_in_rule_space'] - fitted['height'] - fitted['gap']
            tops.append(raised + box['inset_top'])
        # The reason area ends where the first signature paragraph begins,
        # which in the rules' coordinates is minus its height.
        area_top = -self._first_sig_height - area
        return max(0.0, min(area, min(tops) - 1.0 - area_top))

    def write_title(self, label, fitted):
        box = self.boxes[label]
        rise = fitted['height'] + fitted['gap']
        rule = box['rule']
        left = max(0.0, min(rule['centre'] - LABEL_BOX_WIDTH / 2,
                            self.cell_width - LABEL_BOX_WIDTH))
        top = box['top'] - rise
        height = box['height'] + rise

        anchor = box['anchor']
        anchor.find(WP + 'positionV').find(WP + 'posOffset').text = str(int(round(top * EMU)))
        anchor.find(WP + 'positionH').find(WP + 'posOffset').text = str(int(round(left * EMU)))
        for extent in (anchor.find(WP + 'extent'), anchor.find('.//' + A + 'xfrm').find(A + 'ext')):
            extent.set('cx', str(int(round(LABEL_BOX_WIDTH * EMU))))
            extent.set('cy', str(int(round(height * EMU))))
        # "In front of text": the box no longer pushes the reason aside.
        # Its place is kept clear by `reason_room` instead.
        square = anchor.find(WP + 'wrapSquare')
        if square is not None:
            none = OxmlElement('wp:wrapNone')
            square.addprevious(none)
            anchor.remove(square)

        shape = box['shape']
        style = dict(
            part.split(':', 1) for part in shape.get('style').split(';') if ':' in part
        )
        style.update({
            'margin-top': f'{top:.2f}pt', 'margin-left': f'{left:.2f}pt',
            'width': f'{LABEL_BOX_WIDTH:.2f}pt', 'height': f'{height:.2f}pt',
        })
        shape.set('style', ';'.join(f'{k}:{v}' for k, v in style.items()))
        for wrap in shape.iter(W10 + 'wrap'):
            wrap.set('type', 'none')

        for copy_ in box['copies']:
            label_p = next(p for p in copy_.findall(qn('w:p'))
                           if label in ''.join(t.text or '' for t in p.iter(qn('w:t'))))
            title_p = clone(label_p)
            for run in title_p.findall(qn('w:r')):
                title_p.remove(run)
            run = new_run('', fitted['size'], bold=True)
            for i, piece in enumerate(fitted['lines']):
                if i:
                    run.append(OxmlElement('w:br'))
                t = OxmlElement('w:t')
                t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                t.text = piece
                run.append(t)
            title_p.append(run)
            set_spacing(title_p, line_pt=metrics.line_height(fitted['size']))
            set_alignment(title_p, 'center')
            set_mark_size(title_p, fitted['size'])
            label_p.addprevious(title_p)

            set_spacing(label_p, before_pt=fitted['gap'])
            set_alignment(label_p, 'center')


def _text_of_box(txbx):
    return ''.join(t.text or '' for t in txbx.iter(qn('w:t'))).strip()
