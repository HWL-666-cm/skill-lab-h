"""Extract paragraphs and sentences with stable positions from a PDF.

The module uses only the standard library. Reading PDF bytes needs a helper
engine: PyMuPDF when importable, otherwise the `pdftotext` executable. When
neither is available `Unavailable` is raised so the caller can report a blocked
run instead of inventing text.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

SPACE_MAP = {
    "\u00a0": " ", "\u2007": " ", "\u2009": " ", "\u200a": " ",
    "\u202f": " ", "\u2002": " ", "\u2003": " ", "\t": " ",
    "\u200b": "", "\ufeff": "", "\u00ad": "",
}
QUOTE_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2032": "'", "\u2033": '"',
}
LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
}

ABBREV = {
    "al", "fig", "figs", "eq", "eqs", "e.g", "i.e", "vs", "approx", "cf",
    "no", "dr", "mr", "ms", "prof", "ref", "refs", "sec", "tab", "suppl",
    "etc", "min", "max", "ca", "st", "ed", "eds", "vol", "pp", "p", "resp",
    "spp", "var", "subsp", "inc", "ltd", "co", "corp", "dept", "univ",
}


class Unavailable(RuntimeError):
    """No PDF text engine is available on this machine."""


def normalize(text: str) -> str:
    """Collapse whitespace and unify quotes so two spellings compare equal."""
    if not text:
        return ""
    for src, dst in SPACE_MAP.items():
        text = text.replace(src, dst)
    for src, dst in LIGATURES.items():
        text = text.replace(src, dst)
    for src, dst in QUOTE_MAP.items():
        text = text.replace(src, dst)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", text).strip()


def detect_engine() -> str:
    try:
        import pymupdf  # noqa: F401
        return "pymupdf"
    except Exception:
        pass
    try:
        import fitz  # noqa: F401
        return "pymupdf"
    except Exception:
        pass
    if shutil.which("pdftotext"):
        return "pdftotext"
    return ""


def _load_pymupdf(path: Path):
    try:
        import pymupdf as fitz
    except Exception:
        import fitz
    return fitz.open(str(path))


def _is_abbrev(text: str, start: int, dot: int) -> bool:
    k = dot - 1
    while k >= start and (text[k].isalnum() or text[k] in ".&"):
        k -= 1
    word = text[k + 1:dot].lower().strip(".")
    if word in ABBREV:
        return True
    # A single letter is an initial only when capitalised ("J. Smith");
    # lowercase "x's." is a possessive and ends its sentence.
    if len(word) == 1 and word.isalpha():
        raw = text[k + 1:dot].strip(".")
        return raw.isupper()
    return False


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Return (start, end) slices in `text`, split on sentence-final marks."""
    out: list[tuple[int, int]] = []
    start, i, n = 0, 0, len(text)

    def push(a: int, b: int) -> None:
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if a < b:
            out.append((a, b))

    while i < n:
        ch = text[i]
        if ch in "。！？":
            j = i + 1
            while j < n and text[j] in "\"')]}”’":
                j += 1
            push(start, j)
            start, i = j, j
            continue
        if ch in ".!?":
            j = i + 1
            while j < n and text[j] in ".!?\"')]}”’":
                j += 1
            if j >= n or text[j] in " ":
                if ch == "." and _is_abbrev(text, start, i):
                    i = j
                    continue
                k = j
                while k < n and text[k] == " ":
                    k += 1
                if k < n and text[k].islower():
                    i = j
                    continue
                push(start, j)
                start, i = j, j
                continue
        i += 1
    if start < n:
        push(start, n)
    return out


def _join_lines(lines: list[str]) -> str:
    out = ""
    for raw in lines:
        ln = raw.strip()
        if not ln:
            continue
        if out.endswith("-") and len(out) > 1 and ln[0].islower():
            out = out[:-1] + ln
        elif out:
            out = out + " " + ln
        else:
            out = ln
    return out


def _blocks_pymupdf(path: Path) -> list[dict]:
    doc = _load_pymupdf(path)
    pages = []
    try:
        for pno in range(doc.page_count):
            page = doc.load_page(pno)
            raw = page.get_text("dict")
            blocks = []
            for blk in raw.get("blocks", []):
                if blk.get("type", 0) != 0:
                    continue
                lines = []
                sizes = []
                for line in blk.get("lines", []):
                    spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
                    if not spans:
                        continue
                    # Spans often carry no trailing space even when words are
                    # separated visually, so rebuild the gap from the boxes.
                    parts: list[str] = []
                    prev_x1 = None
                    for s in spans:
                        size = float(s.get("size", 0) or 0)
                        x0 = float(s.get("bbox", (0, 0, 0, 0))[0])
                        if prev_x1 is not None and x0 - prev_x1 > 0.18 * max(size, 1.0):
                            parts.append(" ")
                        parts.append(s["text"])
                        prev_x1 = float(s.get("bbox", (0, 0, 0, 0))[2])
                        sizes.append(round(size, 1))
                    lines.append("".join(parts))
                if not lines:
                    continue
                size = max(set(sizes), key=sizes.count) if sizes else 0.0
                blocks.append({
                    "page": pno + 1,
                    "text": _join_lines(lines),
                    "bbox": [round(v, 2) for v in blk.get("bbox", (0, 0, 0, 0))],
                    "size": size,
                })
            meta = doc.metadata or {}
            pages.append({"page": pno + 1, "blocks": blocks, "meta": meta})
    finally:
        doc.close()
    return pages


def _blocks_pdftotext(path: Path) -> list[dict]:
    out = Path(tempfile.mkdtemp(prefix="pdftxt-"))
    try:
        subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(path), str(out / "x.txt")],
            check=True, capture_output=True, timeout=120,
        )
        text = (out / "x.txt").read_text(encoding="utf-8", errors="replace")
    finally:
        shutil.rmtree(out, ignore_errors=True)
    pages = []
    for pno, page_text in enumerate(text.split("\f"), start=1):
        blocks = []
        for chunk in re.split(r"\n\s*\n", page_text):
            chunk = chunk.strip()
            if chunk:
                blocks.append({
                    "page": pno,
                    "text": _join_lines(chunk.splitlines()),
                    "bbox": [0.0, 0.0, 0.0, 0.0],
                    "size": 0.0,
                })
        if blocks:
            pages.append({"page": pno, "blocks": blocks, "meta": {}})
    return pages


def _drop_running_heads(pages: list[dict], min_ratio: float = 0.3) -> None:
    """Remove repeated short blocks (running heads, footers) in place."""
    if len(pages) < 3:
        return
    seen: dict[str, int] = {}
    for pg in pages:
        keys = set()
        for blk in pg["blocks"]:
            key = normalize(blk["text"]).lower()
            if 0 < len(key) <= 80 and not key.endswith((".", "。", "!", "?")):
                keys.add(key)
        for key in keys:
            seen[key] = seen.get(key, 0) + 1
    limit = max(2, int(len(pages) * min_ratio))
    repeated = {k for k, v in seen.items() if v >= limit}
    for pg in pages:
        pg["blocks"] = [b for b in pg["blocks"] if normalize(b["text"]).lower() not in repeated]


class ParsedDocument:
    """Paragraphs, sentences and a normalised full text for quote lookup."""

    def __init__(self, source: Path, paragraphs: list[dict], engine: str, meta: dict):
        self.source = source
        self.paragraphs = paragraphs
        self.engine = engine
        self.meta = meta
        self.normal = normalize("\n".join(p["text"] for p in paragraphs))
        self._starts = []
        cursor = 0
        for p in paragraphs:
            self._starts.append(cursor)
            cursor += len(normalize(p["text"])) + 1

    @property
    def n_sentences(self) -> int:
        return sum(len(p["sentences"]) for p in self.paragraphs)

    def paragraph_at(self, offset: int) -> dict | None:
        lo, hi, hit = 0, len(self._starts) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._starts[mid] <= offset:
                hit = self.paragraphs[mid]
                lo = mid + 1
            else:
                hi = mid - 1
        return hit

    def locate(self, quote: str) -> dict:
        """Find `quote` in the document and report where it sits."""
        nq = normalize(quote)
        result = {
            "found": False, "exact": False, "page": None, "paragraph": None,
            "char_start": None, "char_end": None, "sentence_id": None,
            "matched_text": None,
        }
        if not nq:
            return result
        pos = self.normal.find(nq)
        if pos < 0:
            return result
        para = self.paragraph_at(pos)
        result.update({
            "found": True,
            "exact": True,
            "page": para["page"] if para else None,
            "paragraph": para["pidx"] if para else None,
            "char_start": pos,
            "char_end": pos + len(nq),
            "matched_text": self.normal[pos:pos + len(nq)],
        })
        if para:
            for sent in para["sentences"]:
                if sent["char_start"] is not None and sent["char_start"] <= pos < sent["char_end"]:
                    result["sentence_id"] = sent["id"]
                    break
        return result

    def to_dict(self, with_text: bool = True) -> dict:
        payload = {
            "source": {
                "path": self.source.name,
                "engine": self.engine,
                "n_pages": (self.paragraphs[-1]["page"] if self.paragraphs else 0),
                "n_paragraphs": len(self.paragraphs),
                "n_sentences": self.n_sentences,
                "title": self.meta.get("title") or "",
            },
            "paragraphs": self.paragraphs,
        }
        if with_text:
            payload["normal_text"] = self.normal
        return payload


def parse(path: str | Path) -> ParsedDocument:
    """Parse a PDF into paragraphs whose sentences carry stable char spans."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    engine = detect_engine()
    if not engine:
        raise Unavailable(
            "No PDF text engine found. Install PyMuPDF (`pip install pymupdf`) "
            "or poppler-utils (`pdftotext`)."
        )
    pages = _blocks_pymupdf(path) if engine == "pymupdf" else _blocks_pdftotext(path)
    _drop_running_heads(pages)

    paragraphs: list[dict] = []
    meta: dict = {}
    for pg in pages:
        meta = meta or pg.get("meta", {})
        for blk in pg["blocks"]:
            text = blk["text"].strip()
            if len(text) < 2:
                continue
            pidx = len(paragraphs) + 1
            sentences = []
            for sidx, (a, b) in enumerate(split_sentences(text), start=1):
                frag = text[a:b].strip()
                if len(frag) < 2:
                    continue
                sentences.append({
                    "id": f"P{pidx:03d}S{sidx:02d}",
                    "text": frag,
                    "page": blk["page"],
                    "char_start": None,
                    "char_end": None,
                })
            paragraphs.append({
                "pidx": pidx,
                "page": blk["page"],
                "text": text,
                "bbox": blk["bbox"],
                "sentences": sentences,
            })

    doc = ParsedDocument(path, paragraphs, engine, meta)
    # Fill sentence offsets against the shared normal text so ids stay stable.
    for para in doc.paragraphs:
        base = doc._starts[para["pidx"] - 1]
        cursor = base
        pnormal = normalize(para["text"])
        for sent in para["sentences"]:
            ns = normalize(sent["text"])
            at = pnormal.find(ns, max(0, cursor - base))
            if at < 0:
                at = pnormal.find(ns)
            if at < 0:
                continue
            sent["char_start"] = base + at
            sent["char_end"] = base + at + len(ns)
            cursor = base + at + len(ns)
    return doc


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Parse a PDF into paragraphs and sentences.")
    ap.add_argument("pdf")
    ap.add_argument("--out", help="write JSON here; stdout when omitted")
    args = ap.parse_args(argv)
    try:
        doc = parse(args.pdf)
    except Unavailable as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 3
    payload = json.dumps(doc.to_dict(), ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
