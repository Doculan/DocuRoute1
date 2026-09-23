"""Keeping personal names out of document files.

A Word file carries names nobody sees: who created it, who last saved it,
their company, and whatever they typed into Comments. Names are personal
data under RA 10173, and these ones travel - into version control with a
template, and into every document generated from it, because
`python-docx` copies the template's properties into its output.

So the rule has two halves. **Templates** are scrubbed before they are
committed, and a test keeps them that way. **Generated documents** are
scrubbed as they are made, whatever the template held, so a template
replaced next year with its author still in it cannot leak that name into
every DCR the system prints.

The legacy `.doc` form is binary and is only read here, never generated.
"""

import re
import struct
import zipfile

# The fields Word shows as Author, Last saved by, Comments, Company and
# Manager. Title and dates are not personal and are left alone.
CORE_FIELDS = ('dc:creator', 'cp:lastModifiedBy', 'dc:description')
APP_FIELDS = ('Company', 'Manager')


# --- .docx ---------------------------------------------------

def _personal_in_xml(xml, fields):
    found = {}
    for field in fields:
        match = re.search(r'<%s(?:\s[^>]*)?>([^<]*)</%s>' % (field, field), xml)
        if match and match.group(1).strip():
            found[field] = match.group(1)
    return found


def _cleared(xml, fields):
    for field in fields:
        xml = re.sub(
            r'(<%s(?:\s[^>]*)?>)[^<]*(</%s>)' % (field, field), r'\1\2', xml,
        )
    return xml


def docx_personal_metadata(path_or_file):
    """The personal properties a .docx still carries, as a dict.

    Also reports any `w:author` on tracked changes or comments, which is
    the same name in another place.
    """
    found = {}
    with zipfile.ZipFile(path_or_file) as package:
        names = set(package.namelist())
        if 'docProps/core.xml' in names:
            found.update(_personal_in_xml(
                package.read('docProps/core.xml').decode('utf-8'), CORE_FIELDS,
            ))
        if 'docProps/app.xml' in names:
            found.update(_personal_in_xml(
                package.read('docProps/app.xml').decode('utf-8'), APP_FIELDS,
            ))
        for name in names:
            if name.startswith('word/') and name.endswith('.xml'):
                text = package.read(name).decode('utf-8', 'replace')
                authors = set(re.findall(r'w:author="([^"]+)"', text))
                if authors:
                    found['w:author in ' + name] = sorted(authors)
    return found


def scrub_docx_file(path):
    """Clear the personal properties of a .docx on disk, in place.

    Rewrites only the two property parts; every other entry is copied
    byte for byte, because these are the university's controlled forms.
    """
    import os
    import shutil

    temporary = path + '.scrubbing'
    with zipfile.ZipFile(path) as source, \
            zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == 'docProps/core.xml':
                data = _cleared(data.decode('utf-8'), CORE_FIELDS).encode('utf-8')
            elif info.filename == 'docProps/app.xml':
                data = _cleared(data.decode('utf-8'), APP_FIELDS).encode('utf-8')
            target.writestr(info, data)
    shutil.move(temporary, path)
    if os.path.exists(temporary):
        os.remove(temporary)


def scrub_document(document):
    """Clear the personal properties of a `python-docx` Document before saving.

    `core_properties` covers creator, last saved by and comments. Company
    and Manager live in `app.xml`, which `python-docx` loads as an opaque
    part, so that one is edited as bytes.
    """
    core = document.core_properties
    core.author = ''
    core.last_modified_by = ''
    core.comments = ''

    for part in document.part.package.iter_parts():
        if str(part.partname) == '/docProps/app.xml':
            xml = part.blob.decode('utf-8')
            part._blob = _cleared(xml, APP_FIELDS).encode('utf-8')
    return document


# --- legacy .doc (read only) ---------------------------------

# Property-set identifiers, as they appear on disk (little-endian GUIDs).
_SUMMARY = bytes.fromhex('E0859FF2F94F6810AB9108002B27B3D9')
_DOC_SUMMARY = bytes.fromhex('02D5CDD59C2E1B10939708002B2CF9AE')
# Author, Last saved by, Comments / Manager, Company.
_SUMMARY_IDS = {4: 'Author', 8: 'LastAuthor', 6: 'Comments'}
_DOC_SUMMARY_IDS = {14: 'Manager', 15: 'Company'}
_VT_LPSTR = 30


def _read_property_set(data, fmtid, wanted):
    """The wanted string properties of one property set, or None.

    Reads the section that follows the FMTID. Assumes the stream is
    stored contiguously, which holds for the form in this repository;
    `None` means that assumption failed and the caller should say so
    rather than report the file clean.
    """
    at = data.find(fmtid)
    if at < 0:
        return None
    header_start = at - 28          # byte order ... class id, section count
    if header_start < 0:
        return None
    section_offset = struct.unpack_from('<I', data, at + 16)[0]
    section = header_start + section_offset
    try:
        _size, count = struct.unpack_from('<II', data, section)
        found = {}
        for i in range(count):
            pid, offset = struct.unpack_from('<II', data, section + 8 + 8 * i)
            if pid not in wanted:
                continue
            kind = struct.unpack_from('<I', data, section + offset)[0]
            if kind != _VT_LPSTR:
                continue
            length = struct.unpack_from('<I', data, section + offset + 4)[0]
            raw = data[section + offset + 8: section + offset + 8 + length]
            found[wanted[pid]] = raw.split(b'\x00')[0].decode('cp1252').strip()
        return found
    except struct.error:
        return None


def doc_personal_metadata(path):
    """The personal properties a legacy .doc still carries, as a dict.

    Raises if the property sets cannot be read, so an unreadable file is
    never mistaken for a clean one.
    """
    data = open(path, 'rb').read()
    summary = _read_property_set(data, _SUMMARY, _SUMMARY_IDS)
    doc_summary = _read_property_set(data, _DOC_SUMMARY, _DOC_SUMMARY_IDS)
    if summary is None:
        raise ValueError(f'could not read the summary properties of {path}')
    found = {k: v for k, v in summary.items() if v}
    found.update({k: v for k, v in (doc_summary or {}).items() if v})
    return found
