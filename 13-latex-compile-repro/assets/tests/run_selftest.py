#!/usr/bin/env python3
"""Cold-start self-test.  Run from any directory with only this Skill package.

Covers the real defects found during development so they cannot regress:
  * file-line-error format (./main.tex:8: LaTeX Error: Unicode character ...)
  * multi-pass intermediate warnings must not survive a successful build
  * engine auto-switch on a forced-pdflatex unicode source
  * blocked case with no LaTeX source
  * honesty: unknown output_contract fields become null, never invented
  * determinism of the structured deliverables (PDF bytes excluded by design)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent.parent
SCRIPTS = SKILL / "scripts"
PYTHON = sys.executable
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (" | " + detail if detail else ""))


def run_cli(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    cp = subprocess.run([PYTHON, str(SCRIPTS / "run_case.py")] + args,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        cwd=str(cwd or SKILL), timeout=240)
    return cp.returncode, cp.stdout.decode("utf-8", "replace")


def strip_volatile(obj: dict) -> dict:
    """Remove runtime PDF hashes and timings that legitimately vary."""
    o = json.loads(json.dumps(obj, ensure_ascii=False))
    o.pop("runtime_seconds", None)
    for key in ("reproduce", "build_manifest", "reproduce.json", "build_manifest.json"):
        node = o.get(key)
        if isinstance(node, dict):
            for k in ("original_pdf_sha256", "repro_pdf_sha256", "output_pdf"):
                node.pop(k, None)
    if isinstance(o.get("build_manifest"), dict):
        o["build_manifest"].pop("output_pdf", None)
    return o


def main() -> int:
    lex = SKILL / "assets" / "lexicon.json"
    schema = SKILL / "assets" / "schema.json"
    good = SKILL / "assets" / "examples" / "material" / "good"
    bad = SKILL / "assets" / "examples" / "material" / "bad"
    tmp = Path(tempfile.mkdtemp(prefix="latex_skill_selftest_"))
    try:
        # 1. good source: complete, gate pass, reproduced, no blocking findings
        out = tmp / "good"
        rc, log = run_cli(["--case", str(good), "--out", str(out),
                           "--work", str(tmp / "good_work"),
                           "--lexicon", str(lex), "--schema", str(schema)])
        res = json.loads((out / "result.json").read_text(encoding="utf-8"))
        check("good: complete", res["status"] == "complete", f"rc={rc} status={res['status']}")
        check("good: gate pass", res["validation"]["status"] == "pass",
              str(res["validation"]["counts"]))
        check("good: build converged", res["error_ledger"]["build_ok"] is True)
        check("good: reproduced", res["reproduce"]["verdict"] in ("verified", "partial"),
              res["reproduce"]["verdict"])
        check("good: no blocking findings",
              res["error_ledger"]["counts"].get("blocking", 0) == 0)
        check("good: editable source shipped",
              any(a["path"].endswith(".tex") for a in res["artifacts"]))

        # 2. multi-pass intermediate 'No file main.bbl' must be filtered out
        cats = [f["category"] for f in res["error_ledger"]["findings"]]
        check("good: intermediate bbl warning filtered", "reference" not in cats or
              all("bbl" not in f["log_excerpt"] for f in res["error_ledger"]["findings"]),
              str(cats))

        # 3. bad source forced through pdflatex: engine auto-switch
        out2 = tmp / "bad"
        rc2, log2 = run_cli(["--case", str(bad), "--out", str(out2),
                             "--work", str(tmp / "bad_work"),
                             "--lexicon", str(lex), "--schema", str(schema),
                             "--engine", "pdflatex"])
        res2 = json.loads((out2 / "result.json").read_text(encoding="utf-8"))
        switched = any(c.get("category") == "engine_encoding" and c.get("applied")
                       for c in res2["changes"])
        check("bad: engine auto-switched", switched,
              f"rc={rc2} engine={res2['build_manifest'].get('engine')}")
        check("bad: final build converged", res2["error_ledger"]["build_ok"] is True)
        unresolved = [f for f in res2["error_ledger"]["findings"]
                      if f["severity"] in ("major", "minor")]
        check("bad: unresolved warning is honest",
              bool(unresolved) and bool(res2["uncertainty"]),
              f"{len(unresolved)} warnings, {len(res2['uncertainty'])} uncertainty")
        check("bad: line number located",
              any("input line" in f["location"] for f in unresolved),
              str([f["location"] for f in unresolved]))

        # 3b. source audit: undefined ref is a major issue, and it downgrades status
        aud2 = res2.get("audit", {})
        check("audit: undefined ref detected in source",
              any(f["kind"] == "undefined" for f in aud2.get("findings", [])),
              str(aud2.get("counts")))
        check("audit: major finding downgrades to partial",
              res2["status"] == "partial", res2["status"])
        check("audit: good source is clean",
              res.get("audit", {}).get("counts", {}).get("major", 0) == 0,
              str(res.get("audit", {}).get("counts")))

        # 4. blocked case: empty project
        empty = tmp / "empty_case"
        empty.mkdir()
        out3 = tmp / "empty_out"
        rc3, log3 = run_cli(["--case", str(empty), "--out", str(out3),
                             "--work", str(tmp / "empty_work"),
                             "--lexicon", str(lex), "--schema", str(schema)])
        res3 = json.loads((out3 / "result.json").read_text(encoding="utf-8"))
        check("empty: blocked not fabricated", res3["status"] == "blocked",
              f"rc={rc3} status={res3['status']}")

        # 5. diagnostic coverage with synthetic log lines (file-line form)
        sys.path.insert(0, str(SCRIPTS))
        import diagnose as D  # noqa: E402
        lexicon = json.loads(lex.read_text(encoding="utf-8"))
        synthetic = [
            "./main.tex:8: LaTeX Error: Unicode character β (U+03B2)",
            "! LaTeX Error: File `missing.sty' not found",
            "! Option clash for package biblatex",
            "LaTeX Warning: Citation `abc' on page 1 undefined on input line 4",
            "! Missing $ inserted",
            "Overfull \\hbox (12.3pt too wide) in paragraph at lines 4--6",
            "\\abx@aux@refcontext",
        ]
        cats = set()
        for line in synthetic:
            hits = D._pattern_hits("\n".join([line]), lexicon)
            cats.update(h["category"] for h in hits)
        need = {"engine_encoding", "package", "reference", "math",
                "table_overflow", "stale_aux"}
        check("diagnostics: 6 real-world patterns matched", need <= cats,
              "missing=" + str(sorted(need - cats)))

        # 5b. audit: citation cross-check + layout lint on a synthetic project
        import audit as A  # noqa: E402
        synth = tmp / "audit_synth"
        synth.mkdir()
        (synth / "main.tex").write_text(
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "See \\citet{missing2020} and Table~\\ref{tab:nope}.\n"
            "\\begin{table}[H]\n"
            "\\label{tab:x}\n"          # label and caption on SEPARATE lines
            "\\caption{Shrunk}\n"       # (the real-world form, not one line)
            "\\resizebox{\\textwidth}{!}{\\begin{tabular}{ll}a&b\\end{tabular}}\n"
            "\\end{table}\n"
            "\\begin{figure}[t]\n"
            "\\caption{A scalebox in TikZ.}\n"
            "\\scalebox{0.8}{\\tikz\\node{x};}\n"
            "\\label{fig:ok}\n"         # caption before label: must NOT report
            "\\end{figure}\n"
            "\\bibliographystyle{plain}\\bibliography{refs}\n"
            "\\end{document}\n", encoding="utf-8")
        (synth / "refs.bib").write_text(
            "@article{present2020,author={A},title={T},journal={J},year={2020}}\n",
            encoding="utf-8")
        aud = A.audit_source({"main_tex": str(synth / "main.tex"),
                              "root": str(synth), "files": []})
        kinds = {f["kind"] for f in aud["findings"]}
        check("audit: citation/ref/layout all detected",
              {"missing", "undefined", "shrink_to_fit", "label_before_caption",
               "forced_float", "unused", "scalebox_scaling"} <= kinds,
              "missing=" + str(sorted({"missing", "undefined", "shrink_to_fit",
                                       "label_before_caption", "forced_float",
                                       "unused", "scalebox_scaling"} - kinds)))
        # label-before-caption must be located on the label line (cross-line now)
        lbc = [f for f in aud["findings"] if f["kind"] == "label_before_caption"]
        check("audit: label-before-caption located on label line",
              bool(lbc) and all(":5" in f["location"] for f in lbc),
              str([f["location"] for f in lbc]))
        # scalebox in TikZ is minor, not major
        check("audit: scalebox is minor not major",
              all(f["severity"] == "minor" for f in aud["findings"]
                  if f["kind"] == "scalebox_scaling"))
        # caption-before-label must NOT be flagged as label_before_caption
        check("audit: caption-then-label not misreported",
              not any(f["kind"] == "label_before_caption" and "fig" in f["location"]
                      for f in aud["findings"]))

        # 5c. resolve_case: directory input must honour case.json's material_dir
        import profile as P  # noqa: E402
        raw_dir, root_dir, cid_dir = P.resolve_case(SKILL / "assets" / "examples")
        raw_file, root_file, cid_file = P.resolve_case(
            SKILL / "assets" / "examples" / "case.json")
        check("resolve: directory and case.json pick the same material root",
              root_dir.resolve() == root_file.resolve() and root_dir.name == "good",
              f"dir={root_dir.name} file={root_file.name}")

        # 6. contract honesty: unknown fields become null with a note
        import contract as C  # noqa: E402
        r = {"case_id": "x"}
        r, rep = C.apply(r, ["case_id", "totally_unknown_field"])
        check("contract: unknown field is null, not invented",
              r.get("totally_unknown_field") is None and
              bool(rep["missing"]) and any("not produced" in u for u in r["uncertainty"]),
              str(rep["missing"]))

        # 7. determinism of structured output (PDF timestamp excluded)
        out4 = tmp / "good2"
        rc4, _ = run_cli(["--case", str(good), "--out", str(out4),
                          "--work", str(tmp / "good2_work"),
                          "--lexicon", str(lex), "--schema", str(schema)])
        a = json.loads((out / "result.json").read_text(encoding="utf-8"))
        b = json.loads((out4 / "result.json").read_text(encoding="utf-8"))
        check("determinism: structured result identical",
              strip_volatile(a) == strip_volatile(b), f"rc2={rc4}")

        # 7b. the shipped example result.json must match the current code
        out5 = tmp / "example_out"
        run_cli(["--case", str(SKILL / "assets" / "examples" / "case.json"),
                 "--out", str(out5), "--work", str(tmp / "example_work"),
                 "--lexicon", str(lex), "--schema", str(schema)])
        fresh = json.loads((out5 / "result.json").read_text(encoding="utf-8"))
        ship = json.loads((SKILL / "assets" / "examples" / "result.json")
                          .read_text(encoding="utf-8"))
        check("example: shipped result.json matches current code",
              strip_volatile(fresh) == strip_volatile(ship),
              "示例未随代码重生成（rounds/observations 可能过期）")

        # 8. CLI modules compile
        cp = subprocess.run([PYTHON, "-m", "py_compile"] +
                            [str(p) for p in sorted(SCRIPTS.glob("*.py"))],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        check("all scripts compile", cp.returncode == 0,
              cp.stdout.decode("utf-8", "replace")[:200])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\nSELFTEST {passed}/{len(RESULTS)} passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
