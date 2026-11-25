#!/usr/bin/env python3
"""Material detection and reading.

The runtime contract says: "Read actual files instead of assuming source content
from labels."  So this module never trusts a filename to tell it what is inside.
It looks at the bytes, decides a reader, and records what it actually did.

One output shape for every input format -- a list of *units*:

    {"unit_id", "source", "kind", "locator", "key", "text", "value_text"}

``kind`` is one of manuscript / config / log / code / table / readme / other.
``locator`` is a position a human can go and check: a line number, a key path,
a CSV row, a paragraph index.  Page numbers are never produced: this package
has no reliable way to know them, and inventing one is exactly the failure the
task punishes.

Anything that cannot be read is reported in ``unreadable`` with the reason.  It
is never silently skipped and never guessed at.
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

KINDS_BY_SUFFIX = {
    ".json": "config", ".yaml": "config", ".yml": "config", ".toml": "config",
    ".ini": "config", ".cfg": "config", ".conf": "config", ".env": "config",
    ".csv": "table", ".tsv": "table",
    ".log": "log", ".out": "log", ".err": "log", ".txt": "log",
    ".py": "code", ".sh": "code", ".bash": "code", ".r": "code", ".m": "code",
    ".jl": "code", ".ipynb": "code", ".js": "code", ".ts": "code",
    ".tex": "manuscript", ".md": "manuscript", ".markdown": "manuscript",
    ".rst": "manuscript", ".docx": "manuscript", ".pdf": "manuscript",
    ".html": "manuscript", ".htm": "manuscript",
}

MANUSCRIPT_HINTS = re.compile(
    r"\b(introduction|related work|method|experiment|results?\s+and\s+discussion|"
    r"conclusion|abstract|参考文献|引言|方法|实验|结果|讨论|结论)\b", re.I)
CONFIG_HINTS = re.compile(
    r"^\s*(?:[-\w.]+\s*:\s*|\[\w+\]|-\s+\w)|--[\w-]+\s|=|learning_rate|batch_size", re.I)
LOG_HINTS = re.compile(
    r"(epoch\s*\d|step\s*\d|loss[:=]|acc(uracy)?[:=]|\[INFO\]|\[WARN|\[ERROR|"
    r"Traceback|training complete|saving checkpoint)", re.I)

MAX_BYTES = 4 * 1024 * 1024


def _sniff_kind(path: Path, text: str) -> str:
    """Suffix first, then content.  A .txt of YAML keys is a config, not a log."""
    suffix = path.suffix.lower()
    base = KINDS_BY_SUFFIX.get(suffix, "other")
    head = text[:4000]
    # Markdown/RST is prose by construction. An earlier heuristic counted the
    # `key=value` examples inside a README as config lines and labelled the whole
    # README a config; that would have made prose numbers look like hard sources.
    if suffix in (".md", ".markdown", ".rst"):
        return "manuscript"
    if base in ("log", "other"):
        cfg = len(CONFIG_HINTS.findall(head))
        log = len(LOG_HINTS.findall(head))
        man = len(MANUSCRIPT_HINTS.findall(head))
        if man >= 2 and man >= cfg:
            return "manuscript"
        if cfg >= 3 and cfg > log:
            return "config"
        if log >= 2 and log > cfg:
            return "log"
        if base == "log" and max(cfg, man, log) == 0 and suffix == ".txt":
            return "other"
    return base


def _read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()[:MAX_BYTES]
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8/replace"


# ------------------------------------------------------------------- flattened

def _flatten_json(obj: Any, prefix: str = "", depth: int = 0) -> Iterable[tuple[str, Any]]:
    if depth > 12:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _flatten_json(v, f"{prefix}.{k}" if prefix else str(k), depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _flatten_json(v, f"{prefix}[{i}]", depth + 1)
    else:
        yield prefix, obj


_YAML_KEY = re.compile(r"^(\s*)([-\s]*)([A-Za-z0-9_.\u4e00-\u9fff\"'][^:#]*?)\s*:(?:\s+(.*))?$")


def flatten_yaml(text: str) -> tuple[list[tuple[str, str, int]], list[int]]:
    """Minimal YAML subset: indentation, ``key: value``, ``- item``, block scalars.

    Returns (triples, unparsed_line_numbers).  A line that does not fit the subset
    is reported, not dropped -- the caller falls back to a line regex for it.
    """
    out: list[tuple[str, str, int]] = []
    unparsed: list[int] = []
    stack: list[tuple[int, str]] = []
    block_indent: int | None = None

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if block_indent is not None:
            if indent > block_indent:
                continue                      # inside a | or > block: not a key
            block_indent = None
        m = _YAML_KEY.match(line)
        if not m:
            if line.lstrip().startswith("- "):
                item = line.lstrip()[2:].strip()
                parent = ".".join(k for _, k in stack) or "list"
                if ":" in item and not item.startswith(("http", "'", '"')):
                    k, v = item.split(":", 1)
                    out.append((f"{parent}.{k.strip()}", v.strip(), lineno))
                else:
                    out.append((f"{parent}[{len(out)}]", item, lineno))
                continue
            unparsed.append(lineno)
            continue
        lead, key, value = m.group(1), m.group(3).strip().strip('"\''), (m.group(4) or "").strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = ".".join([k for _, k in stack] + [key]) if stack else key
        if value in ("|", ">", "|-", ">-", "|+", ">+"):
            block_indent = indent
            stack.append((indent, key))
            out.append((path, "", lineno))
            continue
        if value.startswith("#"):
            value = ""
        else:
            hash_at = re.search(r"\s#\s", value)
            if hash_at and not value[:hash_at.start()].count('"') % 2:
                value = value[:hash_at.start()].strip()
        value = value.strip().strip('"\'')
        if value == "":
            stack.append((indent, key))
            out.append((path, "", lineno))
        else:
            out.append((path, value, lineno))
    return out, unparsed


_KV_LINE = re.compile(
    r"""(?P<key>[A-Za-z_][\w.\-]{0,60})\s*(?P<sep>[:=])\s*"""
    r"""(?P<val>-?\d[\d,._eE+\- ]*|true|false|True|False|"[^"]{0,200}"|'[^']{0,200}'|[^\s#;,]{1,80})""")
_FLAG_LINE = re.compile(r"(?P<key>--[A-Za-z][\w\-]{0,40})(?:\s+|=)(?P<val>-?\d[\w.,+\-]*|true|false)")


def kv_from_line(line: str) -> list[tuple[str, str]]:
    """Generic ``key: value`` / ``key=value`` / ``--flag value`` extraction.

    A prose line often carries both shapes at once -- "Quick start: imgsz=640." --
    and the first match swallows the second one, because ``imgsz=640.`` is a
    legal "value".  When that happens the inner pair is what carries the number,
    so it is re-split instead of dropped.  Without this, the documented value in
    a README's quick-start line never reached the ledger.
    """
    found: list[tuple[str, str]] = []
    for m in _KV_LINE.finditer(line):
        val = m.group("val").strip().strip('"\'')
        inner = _KV_LINE.match(val)
        if inner and inner.group("val").strip().strip('"\'') != val:
            found.append((inner.group("key"), inner.group("val").strip().strip('"\'')))
        else:
            found.append((m.group("key"), val))
    if not found:
        found = [(m.group("key").lstrip("-"), m.group("val")) for m in _FLAG_LINE.finditer(line)]
    return found


def units_from_lines(source: str, kind: str, text: str, limit: int = 20000,
                     source_kind: str | None = None) -> list[dict]:
    sk = source_kind or kind
    out: list[dict] = []
    func = ""
    for lineno, line in enumerate(text.splitlines()[:limit], 1):
        if kind == "code":
            m = re.match(r"^\s*(?:async\s+)?def\s+(\w+)", line)
            if m:
                func = m.group(1)
            else:
                m = re.match(r"^\s*class\s+(\w+)", line)
                if m:
                    func = "class_" + m.group(1)
        if not line.strip():
            continue
        out.append({
            "unit_id": "", "source": source, "kind": kind, "source_kind": sk,
            "locator": f"L{lineno}", "key": "", "text": line.strip(),
            "value_text": "", "func": func if kind == "code" else "",
        })
    return out


# ---------------------------------------------------------------- tables

_MD_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_MD_SEP = re.compile(r"^\s*\|[\s:|-]{3,}\|\s*$")
_TEX_ROW = re.compile(r"^\s*(.*?)\\\\\s*$")
_CAPTION = re.compile(r"^\s*(?:Table|TABLE|\u8868)\s*[\dIVX]+[.:\s]", re.I)


def parse_md_tables(text: str, source: str, source_kind: str = "manuscript",
                    caption: str = "") -> tuple[list[dict], set[int]]:
    """Turn a Markdown pipe table into per-cell units keyed by column name.

    Real papers and READMEs put hyper-parameters in tables, where the column name
    *is* the parameter name.  Reading such a row as one free-form line loses that
    binding and produces junk key/value pairs, so tables get their own reader.
    """
    lines = text.splitlines()
    out: list[dict] = []
    consumed: set[int] = set()
    i = 0
    last_caption = ""
    while i < len(lines):
        line = lines[i]
        if _CAPTION.match(line):
            last_caption = line.strip()[:120]
        m = _MD_ROW.match(line)
        if not m or i + 1 >= len(lines) or not _MD_SEP.match(lines[i + 1]):
            i += 1
            continue
        header = [c.strip() for c in m.group(1).split("|")]
        consumed.add(i + 1)
        consumed.add(i + 2)
        j = i + 2
        while j < len(lines) and _MD_ROW.match(lines[j]):
            cells = [c.strip() for c in _MD_ROW.match(lines[j]).group(1).split("|")]
            for c, cell in enumerate(cells):
                if not cell or re.fullmatch(r"[-–—*✗✓]+", cell):
                    continue
                col = header[c] if c < len(header) and header[c] else f"col{c + 1}"
                col = re.sub(r"<[^>]+>", " ", col)
                # "FID-50K (JAX Training)" is FID, not a parameter of its own
                col = re.sub(r"\([^)]*\)", " ", col)
                col = re.sub(r"\s+", " ", col).strip(" *")
                out.append({
                    "unit_id": "", "source": source, "kind": "table",
                    "source_kind": source_kind, "locator": f"L{j + 1}",
                    "key": col, "text": lines[j].strip(), "value_text": cell,
                    "caption": last_caption,
                })
            consumed.add(j + 1)
            j += 1
        i = j
    return out, consumed


def parse_tex_tables(text: str, source: str, source_kind: str = "manuscript") -> tuple[list[dict], set[int]]:
    lines = text.splitlines()
    out: list[dict] = []
    consumed: set[int] = set()
    last_caption = ""
    in_tab = False
    header: list[str] = []
    for idx, line in enumerate(lines):
        if _CAPTION.match(line) or "\\caption{" in line:
            last_caption = line.strip()[:120]
        if re.search(r"\\begin\{(tabular|tabularx|longtable)\}", line):
            in_tab, header = True, []
            consumed.add(idx + 1)
            continue
        if re.search(r"\\end\{(tabular|tabularx|longtable)\}", line):
            in_tab = False
            consumed.add(idx + 1)
            continue
        if not in_tab:
            continue
        consumed.add(idx + 1)
        body = re.sub(r"\\(hline|toprule|midrule|bottomrule|centering)", "", line)
        if "&" not in body:
            continue
        cells = [c.replace("\\\\", "").strip() for c in body.split("&")]
        if not header:
            header = cells
            continue
        for c, cell in enumerate(cells):
            if not cell:
                continue
            col = header[c] if c < len(header) and header[c] else f"col{c + 1}"
            out.append({
                "unit_id": "", "source": source, "kind": "table",
                "source_kind": source_kind, "locator": f"L{idx + 1}",
                "key": re.sub(r"\\[A-Za-z]+\{?|\}|[\${}]", "", col).strip() or f"col{c + 1}",
                "text": line.strip(), "value_text": cell, "caption": last_caption,
            })
    return out, consumed


# ----------------------------------------------------------------------- PDFs

def _pdf_with_pdftotext(path: Path) -> str | None:
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-layout", str(path), "-"], capture_output=True, timeout=120)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.decode("utf-8", "replace")
    except Exception:
        return None
    return None


def _pdf_with_module(path: Path) -> tuple[str | None, str]:
    try:
        import fitz  # type: ignore            # PyMuPDF
        doc = fitz.open(str(path))
        pages = [p.get_text("text") for p in doc]
        doc.close()
        if any(t.strip() for t in pages):
            return "\n".join(pages), "pymupdf"
    except Exception:
        pass
    for mod, attr in (("pypdf", "PdfReader"), ("PyPDF2", "PdfReader")):
        try:
            m = __import__(mod)                      # type: ignore
            reader = getattr(m, attr)(str(path))
            pages = [pg.extract_text() or "" for pg in reader.pages]
            if any(t.strip() for t in pages):
                return "\n".join(pages), mod
        except Exception:
            continue
    try:
        from pdfminer.high_level import extract_text as _ex  # type: ignore
        txt = _ex(str(path))
        if txt.strip():
            return txt, "pdfminer"
    except Exception:
        pass
    return None, ""


_OBJ_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_TEXT_OP = re.compile(rb"\((?:\\.|[^\\()])*\)\s*Tj|\[(?:[^\[\]]|\\.)*\]\s*TJ")


def _pdf_with_stdlib(path: Path) -> str | None:
    """Last resort: inflate content streams and pull the text operators.

    It cannot fix a CID font without the ToUnicode map, so the caller is told the
    result is raw.  Something readable is better than a blank page, and a blank
    page is better than a made-up one.
    """
    import zlib
    data = path.read_bytes()
    chunks: list[str] = []
    for m in _OBJ_STREAM.finditer(data):
        raw = m.group(1)
        try:
            body = zlib.decompress(raw)
        except Exception:
            body = raw
        if b"Tj" not in body and b"TJ" not in body:
            continue
        for op in _TEXT_OP.finditer(body):
            for s in re.findall(rb"\((?:\\.|[^\\()])*\)", op.group(0)):
                txt = s[1:-1]
                txt = re.sub(rb"\\([()\\])", rb"\1", txt)
                txt = txt.replace(b"\\n", b" ").replace(b"\\r", b" ").replace(b"\\t", b" ")
                chunks.append(txt.decode("latin-1", "replace"))
            chunks.append(" ")
        chunks.append("\n")
    joined = "".join(chunks).strip()
    return joined or None


def read_pdf(path: Path) -> tuple[str | None, str, str]:
    txt = _pdf_with_pdftotext(path)
    if txt:
        return txt, "pdftotext", ""
    txt, backend = _pdf_with_module(path)
    if txt:
        return txt, backend, ""
    txt = _pdf_with_stdlib(path)
    if txt:
        return txt, "stdlib-raw", (
            "read with the built-in stream decoder: character encoding may be "
            "unreliable (no ToUnicode map), so treat extracted values as candidates")
    return None, "", "no PDF text backend worked (pdftotext / pymupdf / pypdf / pdfminer / stdlib)"


def _docx_text(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
    except Exception:
        return None
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    lines = []
    for p in root.iter(f"{ns}p"):
        piece = "".join(t.text or "" for t in p.iter(f"{ns}t"))
        if piece.strip():
            lines.append(piece)
    return "\n".join(lines) or None


def _html_text(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"[ \t]{2,}", " ", text)


# --------------------------------------------------------------- material load

def iter_files(root: Path, skip_dirs: set[str], skip_files: set[str] | None = None) -> list[Path]:
    skip_files = skip_files or set()
    files: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in skip_dirs for part in rel.parts[:-1]):
            continue
        relposix = rel.as_posix()
        if (p.name in skip_files or relposix in skip_files
                or any(relposix.startswith(s + "/") for s in skip_files)):
            continue
        files.append(p)
    return files


def read_material(root: Path, skip_dirs: set[str] | None = None,
                  skip_files: set[str] | None = None,
                  extra_roots: list[str] | None = None) -> dict[str, Any]:
    root = Path(root)
    skip = skip_dirs or {"__pycache__", ".git", "node_modules", ".ipynb_checkpoints",
                         "output", "out"}
    skip_files = set(skip_files or ()) | {"case.json", "input.json"}
    units: list[dict] = []
    files: list[dict] = []
    unreadable: list[dict] = []

    candidates = iter_files(root, skip, skip_files)
    if extra_roots:
        # the case says where the material lives; reading the whole tree instead
        # would drag in build output and answer files that are not evidence
        keep = {str(r).strip("/").strip() for r in extra_roots}
        candidates = [p for p in candidates
                      if p.relative_to(root).as_posix().split("/")[0] in keep
                      or len(p.relative_to(root).parts) == 1]

    for path in candidates:
        rel = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        size = path.stat().st_size
        entry = {"source": rel, "suffix": suffix, "bytes": size, "kind": "other",
                 "reader": "", "units": 0, "note": ""}
        try:
            if suffix == ".pdf":
                text, backend, note = read_pdf(path)
                if text is None:
                    unreadable.append({"source": rel, "reason": note})
                    entry["note"] = note
                    files.append(entry)
                    continue
                kind = "manuscript"
                u = units_from_lines(rel, kind, text)
                entry.update(kind=kind, reader=f"pdf:{backend}", note=note)
                units.extend(u)
            elif suffix == ".docx":
                text = _docx_text(path)
                if text is None:
                    unreadable.append({"source": rel, "reason": "docx zip/document.xml unreadable"})
                    entry["note"] = "unreadable"
                    files.append(entry)
                    continue
                u = units_from_lines(rel, "manuscript", text)
                entry.update(kind="manuscript", reader="docx-xml")
                units.extend(u)
            elif suffix in (".json",):
                text, _enc = _read_text(path)
                try:
                    obj = json.loads(text)
                except json.JSONDecodeError as exc:
                    unreadable.append({"source": rel, "reason": f"invalid JSON: {exc}"})
                    entry["note"] = "invalid JSON"
                    files.append(entry)
                    continue
                flat = list(_flatten_json(obj))
                for i, (key, val) in enumerate(flat):
                    units.append({
                        "unit_id": "", "source": rel, "kind": "config",
                        "locator": f"key:{key}" if key else f"item:{i}",
                        "key": key, "text": f"{key}: {val}", "value_text": str(val),
                    })
                entry.update(kind="config", reader="json", units=len(flat))
            elif suffix in (".yaml", ".yml"):
                text, _enc = _read_text(path)
                triples, bad = flatten_yaml(text)
                for key, val, lineno in triples:
                    units.append({
                        "unit_id": "", "source": rel, "kind": "config",
                        "locator": f"L{lineno}", "key": key,
                        "text": (text.splitlines()[lineno - 1].strip() if lineno <= len(text.splitlines()) else f"{key}: {val}"),
                        "value_text": val,
                    })
                for lineno in bad:
                    line = text.splitlines()[lineno - 1].strip()
                    units.append({
                        "unit_id": "", "source": rel, "kind": "config",
                        "locator": f"L{lineno}", "key": "", "text": line, "value_text": "",
                    })
                entry.update(kind="config", reader="yaml-subset", units=len(triples),
                             note=f"{len(bad)} lines outside the yaml subset" if bad else "")
            elif suffix in (".csv", ".tsv"):
                text, _enc = _read_text(path)
                delim = "\t" if suffix == ".tsv" else ","
                rows = list(csv.reader(io.StringIO(text), delimiter=delim))
                header = rows[0] if rows else []
                for r, row in enumerate(rows[1:], 2):
                    for c, cell in enumerate(row):
                        if not str(cell).strip():
                            continue
                        col = header[c] if c < len(header) else f"col{c + 1}"
                        units.append({
                            "unit_id": "", "source": rel, "kind": "table",
                            "locator": f"row{r}", "key": col,
                            "text": f"{col}={cell} (row {r})", "value_text": str(cell),
                        })
                entry.update(kind="table", reader="csv", units=len(units))
            elif suffix == ".ipynb":
                text, _enc = _read_text(path)
                try:
                    nb = json.loads(text)
                except json.JSONDecodeError:
                    unreadable.append({"source": rel, "reason": "invalid notebook JSON"})
                    entry["note"] = "invalid notebook"
                    files.append(entry)
                    continue
                body = []
                for cell in nb.get("cells") or []:
                    src = cell.get("source")
                    body.append("".join(src) if isinstance(src, list) else str(src or ""))
                entry.update(kind="code", reader="notebook")
                units.extend(units_from_lines(rel, "code", "\n".join(body)))
            elif suffix in (".html", ".htm"):
                text, _enc = _read_text(path)
                plain = _html_text(text)
                entry.update(kind="manuscript", reader="html-strip")
                units.extend(units_from_lines(rel, "manuscript", plain))
            else:
                text, enc = _read_text(path)
                kind = _sniff_kind(path, text)
                entry.update(kind=kind, reader=f"text/{enc}")
                rows: list[dict] = []
                consumed: set[int] = set()
                if suffix in (".md", ".markdown", ".rst"):
                    rows, consumed = parse_md_tables(text, rel)
                elif suffix == ".tex":
                    rows, consumed = parse_tex_tables(text, rel)
                if rows:
                    entry["note"] = f"{len(rows)} table cells bound to column names"
                units.extend(rows)
                for u in units_from_lines(rel, kind, text):
                    if int(u["locator"][1:]) not in consumed:
                        units.append(u)
        except Exception as exc:                 # one bad file must not stop the run
            unreadable.append({"source": rel, "reason": f"{type(exc).__name__}: {exc}"})
            entry["note"] = "reader crashed"
        if not entry["units"]:
            entry["units"] = sum(1 for u in units if u["source"] == rel)
        files.append(entry)

    # Every unit records where it came from in the source hierarchy, because the
    # provenance grade (config / log / code / manuscript) drives how much a value
    # is trusted later. A table cell inherits the grade of the file it sits in.
    _SK = {"manuscript": "manuscript", "readme": "manuscript", "config": "config",
           "log": "log", "code": "code", "table": "config", "other": "other"}
    for i, u in enumerate(units, 1):
        u["unit_id"] = f"u{i:05d}"
        if not u.get("source_kind"):
            u["source_kind"] = _SK.get(u["kind"], "other")

    by_source: dict[str, list[dict]] = {}
    for u in units:
        by_source.setdefault(u["source"], []).append(u)

    return {
        "root": str(root),
        "files": files,
        "units": units,
        "by_source": by_source,
        "unreadable": unreadable,
        "stats": {
            "files": len(files),
            "units": len(units),
            "unreadable": len(unreadable),
            "kinds": {k: sum(1 for f in files if f["kind"] == k)
                      for k in ("manuscript", "config", "log", "code", "table", "readme", "other")},
        },
    }


if __name__ == "__main__":
    import sys
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    pack = read_material(root)
    print(json.dumps(pack["stats"], ensure_ascii=False, indent=2))
    for f in pack["files"]:
        print(f"  {f['source']:48} {f['kind']:10} {f['reader']:14} {f['units']:6} {f['note']}")
    for u in pack["unreadable"]:
        print("  UNREADABLE", u)
