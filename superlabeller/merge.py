"""Field placeholders ("mail merge") for label elements.

Write {Column} in a text, barcode or QR element and it is replaced by that
column's value for each record. An optional format follows a colon:

    {Price:.2f}      number formatting (Python format spec)
    {Serial:06d}     zero-padded number
    {MfgDate:%d/%m/%Y}  date formatting (strftime)

Built-in fields: {_row} record number (1-based), {_count} number of records,
{_date} today's date, {_time} current time. Unknown fields are left as typed.
"""
import datetime
import decimal
import re

FIELD_RE = re.compile(r"\{([^{}:]+?)(?::([^{}]*))?\}")
MERGE_KEYS = {"text": ("text",), "barcode": ("data",), "qr": ("data",)}
SPECIAL_FIELDS = ["_row", "_count", "_date", "_time"]
DEFAULT_DATE = "%d-%m-%Y"
_MISSING = object()


def format_value(v, fmt=None):
    if v is None:
        return ""
    if isinstance(v, datetime.datetime):
        if fmt:
            return v.strftime(fmt)
        return v.strftime(DEFAULT_DATE + (" %H:%M" if (v.hour or v.minute) else ""))
    if isinstance(v, datetime.date):
        return v.strftime(fmt or DEFAULT_DATE)
    if isinstance(v, datetime.time):
        return v.strftime(fmt or "%H:%M")
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, (int, float, decimal.Decimal)) and not isinstance(v, bool):
        if fmt:
            try:
                return format(v, fmt)
            except (ValueError, TypeError):
                pass
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)
    s = str(v)
    if fmt:
        # Text from CSV files: try it as a number first so {Price:.2f} still works.
        try:
            return format(float(s) if "." in s or "e" in s.lower() else int(s), fmt)
        except (ValueError, TypeError):
            try:
                return format(s, fmt)
            except (ValueError, TypeError):
                pass
    return s


def _lookup(record, name):
    if not record:
        return _MISSING
    if name in record:
        return record[name]
    low = name.lower()
    for k, v in record.items():
        if k.lower() == low:
            return v
    return _MISSING


def merge_text(s, record=None, index=0, count=1):
    if "{" not in s:
        return s

    def rep(m):
        name, fmt = m.group(1).strip(), m.group(2)
        if name == "_row":
            return format_value(index + 1, fmt)
        if name == "_count":
            return format_value(count, fmt)
        if name == "_date":
            return datetime.date.today().strftime(fmt or DEFAULT_DATE)
        if name == "_time":
            return datetime.datetime.now().strftime(fmt or "%H:%M")
        v = _lookup(record, name)
        return m.group(0) if v is _MISSING else format_value(v, fmt)

    return FIELD_RE.sub(rep, s)


def merge_element(el, record=None, index=0, count=1):
    """The element with placeholders filled in (the original if it has none)."""
    keys = MERGE_KEYS.get(el["type"], ())
    if not any("{" in el[k] for k in keys):
        return el
    out = dict(el)
    for k in keys:
        out[k] = merge_text(el[k], record, index, count)
    return out


def merge_doc(doc, record=None, index=0, count=1):
    out = dict(doc)
    out["elements"] = [merge_element(e, record, index, count) for e in doc["elements"]]
    return out


def fields_used(doc):
    names = []
    for el in doc["elements"]:
        for k in MERGE_KEYS.get(el["type"], ()):
            for m in FIELD_RE.finditer(el[k]):
                n = m.group(1).strip()
                if n not in names:
                    names.append(n)
    return names
