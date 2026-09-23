"""Measuring text before Word lays it out.

The DCR is a one-page form whose rows grow when their content does, so
anything written into it has to be known to fit before it is written: a
row that grows pushes sections 3 to 5 onto a second page, and the form
then prints across two sheets.

Two things make the measurement safe rather than approximate.

**Line height is set, not predicted.** Every paragraph generation writes
uses exact line spacing, so its height is the number of lines times a
number chosen here. Only the line count depends on the font.

**Every approximation errs towards more lines.** Breaks are taken at spaces
only, though Word will also break after a hyphen; unknown characters are
measured as the widest letter; and the available width is reduced by a
margin. Counting a line too many leaves a little white space. Counting one
too few is the failure this module exists to prevent.
"""

from .arial_widths import BOLD, REGULAR

# Word's single spacing for Arial and Times New Roman, as a multiple of
# the font size: ascender, descender and line gap from the fonts' own
# tables. Also the factor used to *set* exact spacing, so the form's
# existing rhythm is kept.
LINE_FACTOR = 1.15

# Taken off every available width before wrapping.
SAFETY_PT = 4.0

_WIDEST = {'regular': REGULAR['W'], 'bold': BOLD['W']}


def text_width(text, size, bold=False):
    """Width in points of `text` in Arial at `size` points."""
    table = BOLD if bold else REGULAR
    widest = _WIDEST['bold' if bold else 'regular']
    return sum(table.get(ch, widest) for ch in text) * size / 1000.0


def line_height(size):
    """The exact line spacing generation uses for this size, in points."""
    return round(LINE_FACTOR * size, 2)


def wrap(text, width, size, bold=False):
    """Split one paragraph of text into the lines Word would at most need.

    Greedy, breaking at spaces. A word wider than the line is split by
    characters, as Word does.
    """
    available = width - SAFETY_PT
    lines, current = [], ''
    for word in text.split(' '):
        candidate = word if not current else current + ' ' + word
        if text_width(candidate, size, bold) <= available:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ''
        while text_width(word, size, bold) > available:
            cut = len(word)
            while cut > 1 and text_width(word[:cut], size, bold) > available:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    lines.append(current)
    return lines


def lines_needed(paragraphs, width, size, bold=False):
    """Total lines for several paragraphs, each starting on a new line."""
    return sum(len(wrap(p, width, size, bold)) for p in paragraphs)


def fit(paragraphs, width, height, sizes, bold=False):
    """The largest size at which the paragraphs fit, or None.

    Returns (size, lines) so the caller can size the spacer it adds
    beneath them.
    """
    for size in sizes:
        count = lines_needed(paragraphs, width, size, bold)
        if count * line_height(size) <= height:
            return size, count
    return None


def fit_one_line(text, width, sizes, bold=False):
    """The largest size at which `text` fits on one line, or None."""
    for size in sizes:
        if text_width(text, size, bold) <= width - SAFETY_PT:
            return size
    return None
