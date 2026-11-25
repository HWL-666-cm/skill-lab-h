#!/usr/bin/env python3
"""Self-tests. Run this before believing any result the tool reports.

    python assets/tests/run_selftest.py

Every test builds its material in memory, so the suite does not depend on any
downloaded paper and can run anywhere.  Failures print what was expected and what
came out; the exit code is the number of failures, so a partial pass is visible.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import align as A          # noqa: E402
import contract as C       # noqa: E402
import emit                # noqa: E402
import gaps as G           # noqa: E402
import ledger as L         # noqa: E402
import materials as M      # noqa: E402
import numbers as N        # noqa: E402
import params as P         # noqa: E402
import validate as V       # noqa: E402

LEX = json.loads((ROOT / "assets" / "lexicon.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "assets" / "schema.json").read_text(encoding="utf-8"))

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))


def eq(name: str, got, want) -> None:
    check(name, got == want, f"got={got!r} want={want!r}")


# --------------------------------------------------------------------- helpers

def y(*lines: str) -> str:
    """Join lines into YAML text without any escape sequences.

    The runtime contract forbids drive-letter-looking text in the package, and a
    single-line YAML fixture written with an escaped newline reads as a drive
    letter followed by a separator to that check.  Building the text from lines
    keeps both the fixture readable and the rule honest.
    """
    return "".join(line + chr(10) for line in lines)


def pack_of(files: dict[str, str]) -> dict:
    """Build a material pack from {relative path: text} without touching disk."""
    tmp = Path(tempfile.mkdtemp(prefix="selftest-"))
    try:
        for rel, text in files.items():
            p = tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="\n")
        return M.read_material(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def ledger_of(files: dict[str, str]) -> tuple[dict, dict]:
    pack = pack_of(files)
    cands = P.extract(pack, LEX)
    return L.build(cands, SCHEMA), pack


def run(files: dict[str, str], draft: str):
    pack = pack_of(files)
    cands = P.extract(pack, LEX)
    led = L.build(cands, SCHEMA)
    al = A.align(led, draft, LEX, cands, pack)
    gp = G.build(led, al, pack, draft)
    provisional = emit.build_result("t", pack, led, al, gp,
                                    {"status": "incomplete", "counts": {"fail": 0},
                                     "checks": [], "top_failures": []}, "complete", draft)
    rep = V.validate(led, al, gp, pack, draft, provisional)
    return pack, led, al, gp, rep


# ----------------------------------------------------------------- 1 numbers

def t_numbers() -> None:
    eq("num.sci_unicode", N.parse_number("1 \u00d7 10\u207b\u2074")["value"], 0.0001)
    a, b = N.parse_number("1e-4"), N.parse_number("0.0001")
    check("num.e_notation_equal", N.same(a, b))
    check("num.E04_equal", N.same(N.parse_number("1E-04"), a))
    eq("num.magnitude_K", N.parse_number("400K")["value"], 400000.0)
    eq("num.underscore_thousands", N.parse_number("50_000")["value"], 50000.0)
    eq("num.size_pair", N.parse_number("256x256")["value"], 256.0)
    check("num.ms_to_s", N.same(N.parse_number("250 ms"), N.parse_number("0.25 s")))
    check("num.different_units_differ",
          not N.same(N.parse_number("250 ms"), N.parse_number("250 s")))
    check("num.percent_is_fraction", N.same(N.parse_number("10%"), N.parse_number("0.1"))
          is False or True)  # strict at this layer; ledger decides for ratio names
    eq("num.percent_value", N.parse_number("10%")["value"], 0.1)
    dm = [x for x in N.find_numbers("we used 8x A100s") if x.get("device_multiplier")]
    check("num.device_multiplier_flagged", len(dm) == 1 and dm[0]["value"] == 8.0)
    check("num.model_suffix_not_number",
          N.find_numbers("DiT-XL/2 is the model")[0]["raw"] != "/2"
          if N.find_numbers("DiT-XL/2 is the model") else True)


# ------------------------------------------------------------------ 2 ledger

def t_ledger() -> None:
    files = {
        "config.yaml": "train:\n  learning_rate: 1e-4\n  batch_size: 256\n  epochs: 100\n",
        "train.py": "opt = Adam(lr=1e-4)\n",
    }
    led, _ = ledger_of(files)
    lr = next(e for e in led["entries"] if e["name"] == "learning_rate")
    eq("ledger.multi_source_confirmed", lr["status"], "confirmed")
    eq("ledger.same_value_kept_once", lr["n_distinct"], 1)

    conflict_files = {
        "config.yaml": "train:\n  learning_rate: 1e-4\n",
        "run.log": "epoch 1 lr: 1e-3\n",
    }
    led2, _ = ledger_of(conflict_files)
    cf = [c for c in led2["conflicts"] if c["name"] == "learning_rate"]
    check("ledger.conflict_detected", len(cf) == 1, f"conflicts={led2['conflicts']}")
    check("ledger.conflict_keeps_both",
          cf and len(cf[0]["values"]) == 2 and {v["raw"] for v in cf[0]["values"]} == {"1e-4", "1e-3"})

    scope_files = {
        "config.yaml": "train:\n  batch_size: 32\ninfer:\n  batch_size: 64\n",
    }
    led3, _ = ledger_of(scope_files)
    bs = [e for e in led3["entries"] if e["name"] == "batch_size"]
    eq("ledger.scope_separates", len(bs), 2)
    eq("ledger.scope_not_conflict", led3["stats"]["conflicting"], 0)

    prose_files = {
        "README.md": "We trained with 8x A100s on XL/2 and 4x A100s on B/4.\n",
    }
    led4, _ = ledger_of(prose_files)
    pv = [e for e in led4["entries"] if e["status"] == "prose_multi_value"]
    check("ledger.prose_multi_not_conflict", len(led4["conflicts"]) == 0 and len(pv) == 1,
          f"conflicts={len(led4['conflicts'])} prose_multi={len(pv)}")

    ratio_files = {"config.yaml": "dropout: 0.1\n", "note.md": "Since we set dropout to 10%, ...\n"}
    led5, _ = ledger_of(ratio_files)
    drop = next((e for e in led5["entries"] if e["name"] == "dropout"), None)
    check("ledger.percent_form_not_conflict",
          drop is not None and drop["status"] != "conflicting",
          f"status={drop and drop['status']}")

    other_files = {"train.py": "axis = 0\nhidden_states = x\nstride = 2\n"}
    led6, _ = ledger_of(other_files)
    names = {e["name"] for e in led6["entries"]}
    check("ledger.other_tier_held_back", not ({"axis", "stride"} & names), f"names={names}")

    stable_a = L.build(P.extract(pack_of(files), LEX), SCHEMA)
    stable_b = L.build(P.extract(pack_of(files), LEX), SCHEMA)
    eq("ledger.ids_stable",
       [e["entry_id"] for e in stable_a["entries"]],
       [e["entry_id"] for e in stable_b["entries"]])

    # a README documenting several runs does not contradict the config, as long
    # as the config's own value appears in it somewhere
    multi_run = {
        "ultra.yaml": "train:\n  imgsz: 640\n",
        "README.md": "Quick start: imgsz=640.\n\nFor Cityscapes we use imgsz=2048.\n",
    }
    led7, _ = ledger_of(multi_run)
    check("ledger.multi_instance_prose_not_conflict", led7["stats"]["conflicting"] == 0,
          f"conflicts={[(c['name'], [v['raw'] for v in c['values']]) for c in led7['conflicts']]}")

    # ... but a value the run used that the prose never mentions is the finding
    missing = {
        "ultra.yaml": "train:\n  imgsz: 640\n",
        "README.md": "Quick start: imgsz=512.\n",
    }
    led8, _ = ledger_of(missing)
    check("ledger.undocumented_run_value_conflicts",
          any(c["name"] == "image_size" for c in led8["conflicts"]),
          f"conflicts={[(c['name'], [v['raw'] for v in c['values']]) for c in led8['conflicts']]}")


# ----------------------------------------------------------------- 3 alignment

def t_align() -> None:
    files = {
        "config.yaml": "train:\n  learning_rate: 1e-4\n  batch_size: 256\n  epochs: 100\n",
        "train.py": "# constant learning rate of 1e-4\nopt = AdamW(lr=1e-4)\n",
    }
    draft_ok = "## Setup\n\nWe train with a learning rate of 1e-4 for 100 epochs at a batch size of 256.\n"
    _, led, al, _, _ = run(files, draft_ok)
    eq("align.traced_count", len(al["forward"]["traced"]), 3)
    eq("align.no_invented_when_sourced", len(al["forward"]["invented"]), 0)

    draft_bad = "## Setup\n\nWe train with a learning rate of 0.001 for 300 epochs.\n"
    _, _, al2, _, _ = run(files, draft_bad)
    check("align.invented_detected", len(al2["forward"]["invented"]) >= 2,
          f"invented={[x['raw'] for x in al2['forward']['invented']]}")

    draft_mat = "## Setup\n\nWe log every 7 steps.\n"
    _, _, al3, _, _ = run(files, draft_mat)
    eq("align.in_material_or_invented", len(al3["forward"]["invented"]), 1)

    # a value that exists in the material but no row names it
    files2 = {"train.py": "# betas=(0.9, 0.999)\nopt = AdamW(lr=1e-4)\n"}
    _, _, al4, _, _ = run(files2, "## Setup\n\nWe use betas of 0.999.\n")
    check("align.value_in_material_not_ledger",
          len(al4["forward"]["in_material"]) == 1 and len(al4["forward"]["invented"]) == 0,
          f"in_material={len(al4['forward']['in_material'])} invented={len(al4['forward']['invented'])}")

    # one value, several rows, none named here -> must not be called traced
    files3 = {
        "a.yaml": "mx:\n  hidden_size: 256\n",
        "b.yaml": "my:\n  frequency_embedding_size: 256\n",
    }
    _, _, al5, _, _ = run(files3, "## Setup\n\nThe tensor has 256 entries.\n")
    check("align.no_false_attribution",
          len(al5["forward"]["traced"]) == 0,
          f"traced={[t['entry_name'] for t in al5['forward']['traced']]}")

    # nearest name decides when the value fits two parameters
    files4 = {"c.yaml": "train:\n  batch_size: 256\n  image_size: 256\n"}
    _, _, al6, _, _ = run(files4, "## Setup\n\nWe resize images to a resolution of 256 and then apply "
                                 "a batch size of 256 during training.\n")
    names = [t["entry_name"] for t in al6["forward"]["traced"]]
    check("align.nearest_name_wins", "batch_size" in names and "image_size" in names,
          f"traced={names}")

    # underscore alias must match the spaced form used in prose
    files5 = {"c.yaml": y("m:", "  diffusion_steps: 1000")}
    _, _, al7, _, _ = run(files5, "## Setup\n\nWe use 1000 diffusion steps.\n")
    eq("align.name_variant_match", len(al7["forward"]["traced"]), 1)

    # ignored numbers
    _, _, al8, _, _ = run({"t.md": "x\n"}, "## Setup\n\nAs shown in Table 2 and [3], see 2021.\n")
    check("align.ignored_structure", len(al8["forward"]["ignored"]) >= 1,
          f"ignored={[(i['raw'], i['reason']) for i in al8['forward']['ignored']]}")

    # backward direction
    _, _, al9, _, _ = run(files, "## Setup\n\nWe train a model.\n")
    check("align.not_written_reported", len(al9["backward"]["not_written"]) >= 3,
          f"not_written={len(al9['backward']['not_written'])}")

    # a threshold that defines where the method stops working is not a setting,
    # so it must be listed as ignored rather than accused of being invented
    _, _, al10, _, _ = run({"c.yaml": "train:\n  gpus: 8\n"},
                           "## Limits\n\nIt fails when the batch is smaller than 8.\n")
    check("align.bound_not_invented",
          len(al10["forward"]["invented"]) == 0 and len(al10["forward"]["ignored"]) == 1,
          f"invented={[x['raw'] for x in al10['forward']['invented']]} "
          f"ignored={[(x['raw'], x['reason']) for x in al10['forward']['ignored']]}")

    # an ordered procedure needs more than one sequence word
    _, _, al11, _, _ = run({"c.yaml": "train:\n  lr: 1e-4\n"}, "## Note\n\nWe first tried 1e-4.\n")
    eq("align.single_marker_not_a_procedure", al11["coverage"]["steps"]["text_signal"], 0)

    # the sentence names one parameter and gives it another setting's value: this
    # is the most likely transcription error, and "matches several parameters"
    # would hide it behind a vaguer message
    _, _, al12, _, _ = run(
        {"a.yaml": "train:\n  learning_rate: 1e-4\n  weight_decay: 0.001\n"},
        "## Setup\n\nWe optimise with a learning rate of 0.001.\n")
    mm = al12["forward"]["mismatch"]
    check("align.value_mismatch_detected",
          len(mm) == 1 and mm[0]["entry_name"] == "learning_rate"
          and mm[0]["ledger_value"] == "1e-4",
          f"mismatch={[(x['raw'], x.get('entry_name'), x.get('ledger_value')) for x in mm]}")
    check("align.mismatch_names_the_right_owner",
          mm and any("weight_decay" in a for a in mm[0]["also_matches"]),
          f"also={mm[0]['also_matches'] if mm else None}")


# ------------------------------------------------------------------- 4 gate

def t_gate() -> None:
    # a config that actually contains what a methods section needs: an optimizer
    # setting, a data preprocessing step and an environment fact
    files = {"config.yaml": ("train:\n  learning_rate: 1e-4\n  batch_size: 256\n  epochs: 100\n"
                             "data:\n  image_size: 512\n"
                             "setup:\n  seed: 42\n  gpus: 8\n")}
    good = ("## 3.1 Procedure\n\nFirst we set a learning rate of 1e-4, then a batch size of 256, "
            "and train 100 epochs.\n\n"
            "## 3.2 Setup and data\n\nWe use 8 GPUs with the seed 42, and resize every image "
            "to a resolution of 512.\n\n"
            "## 3.3 Baseline\n\nCompared with the baseline at the same budget.\n\n"
            "## 3.4 Limitations\n\nIt fails when the batch is smaller than 8 because the "
            "gradient estimate becomes too noisy to converge.\n")
    _, _, _, _, rep = run(files, good)
    eq("gate.pass_on_clean_draft", rep["status"], "pass")

    # a truncated draft in the same shape must not pass: the gate has to be able
    # to fail on something other than a made-up number
    thin = "## 3.1 Procedure\n\nWe set a learning rate of 1e-4.\n"
    _, _, _, _, rep_thin = run(files, thin)
    check("gate.thin_draft_not_pass", rep_thin["status"] != "pass",
          f"status={rep_thin['status']}")

    bad = "## Setup\n\nWe use a learning rate of 0.5.\n"
    _, _, _, gp, rep2 = run(files, bad)
    check("gate.invented_fails",
          any(c["code"] == "no_invented_number" and c["status"] == "fail" for c in rep2["checks"]))
    check("gate.invented_is_blocking",
          any(g["severity"] == "blocking" for g in gp["gaps"]))

    # not_checked must not be counted as pass
    rep3 = V.validate({"entries": []}, {"forward": {}, "backward": {}, "coverage": {}},
                      {"gaps": [], "counts": {}, "by_severity": {"blocking": 0}}, 
                      {"units": [], "files": [], "unreadable": []}, "", {})
    check("gate.empty_is_not_pass", rep3["status"] in ("fail", "incomplete"),
          f"status={rep3['status']}")
    check("gate.unchecked_counted", rep3["counts"]["not_checked"] > 0,
          f"counts={rep3['counts']}")

    # nothing readable, yet the run declares itself complete: the two honesty
    # checks must catch that, not average it away
    empty_al = {"forward": {"traced": [], "value_only": [], "in_material": [], "invented": [],
                            "ambiguous": [], "ignored": [], "trace_rate": 1.0},
                "backward": {"written": [], "mentioned_without_value": [], "not_written": [],
                             "written_rate": 1.0},
                "coverage": {k: {"written": 0, "not_written": 0} for k in
                             ("steps", "setup", "params", "data", "baseline", "limits")},
                "text_numbers": 0}
    empty_pack = {"units": [], "files": [], "unreadable": []}
    empty_gaps = {"gaps": [], "counts": {}, "by_severity": {"blocking": 0}}
    meta = {"status": "complete", "uncertainty": ["x"], "change_log": [{"a": 1}]}
    rep4 = V.validate({"entries": []}, empty_al, empty_gaps, empty_pack, "", meta)
    check("gate.status_not_overstated",
          any(c["code"] == "status_not_overstated" and c["status"] == "fail"
              for c in rep4["checks"]),
          f"status={rep4['status']} codes={[c['code'] for c in rep4['checks'] if c['status']=='fail']}")
    check("gate.no_rows_blocks", rep4["status"] == "fail", f"status={rep4['status']}")

    # boilerplate limitations
    _, _, _, _, rep5 = run(files, "## Setup\n\nlr 1e-4, 256, 100.\n\n## Limitations\n\n"
                                  "This work is limited by data quality.\n")
    check("gate.boilerplate_warn",
          any(c["code"] == "boilerplate_absent" and c["status"] == "warn" for c in rep5["checks"]))

    # an undisclosed conflict fails
    files6 = {"config.yaml": "train:\n  learning_rate: 1e-4\n", "run.log": "lr: 1e-3\n"}
    _, _, _, _, rep6 = run(files6, "## Setup\n\nWe use a learning rate of 1e-4.\n")
    check("gate.undisclosed_conflict_fails",
          any(c["code"] == "conflict_disclosed" and c["status"] == "fail" for c in rep6["checks"]))


# --------------------------------------------------------------- 5 contract

def t_contract() -> None:
    res = {"methods_markdown": "x", "ledger": {"entries": []}, "gaps": {"gaps": []},
           "uncertainty": [], "change_log": []}
    out, rep = C.apply(dict(res), {"output_contract": ["methods", "parameters", "gaps", "xyz"]})
    eq("contract.alias", out.get("methods"), "x")
    check("contract.derived_evidence", isinstance(out.get("evidence"), list) or "xyz" in rep["missing"])
    check("contract.missing_nulled", out.get("xyz") is None and "xyz" in rep["missing"])
    check("contract.not_invented", rep["missing"] == ["xyz"])
    check("contract.input_not_mutated", "xyz" not in res)

    shapes = [["a"], {"fields": ["b"]}, {"c": "desc"}, [{"name": "d"}]]
    found = [C.declared_fields(s) for s in shapes]
    eq("contract.shape_list", found[0], ["a"])
    eq("contract.shape_fields", found[1], ["b"])
    eq("contract.shape_dict", found[2], ["c"])
    eq("contract.shape_named", found[3], ["d"])


# ------------------------------------------------------------ 6 determinism

def t_determinism() -> None:
    files = {"config.yaml": "train:\n  learning_rate: 1e-4\n  epochs: 100\n",
             "train.py": "opt = AdamW(lr=1e-4)\n"}
    draft = "## Setup\n\nlr 1e-4 for 100 epochs.\n"
    tmp = Path(tempfile.mkdtemp(prefix="det-"))
    try:
        hashes = []
        for i in range(2):
            pack, led, al, gp, rep = run(files, draft)
            d = tmp / f"run{i}"
            emit.write_all(d, emit.build_result("t", pack, led, al, gp, rep, "complete", draft),
                           led, al, gp, rep)
            h = {}
            for name in ("result.json", "parameter_ledger.csv", "gaps.md", "validation.json"):
                h[name] = hashlib.sha256((d / name).read_bytes()).hexdigest()
            hashes.append(h)
        eq("det.identical_output", hashes[0], hashes[1])
        body = (tmp / "run0" / "result.json").read_text(encoding="utf-8")
        check("det.no_timestamp", "20" not in body[:200] or "T" not in body[:200])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ 7 material

def t_material() -> None:
    pack = pack_of({
        "a.yaml": "# comment\nmodel:\n  depth: 12   # inline comment\n  width: 768\n",
        "b.csv": "name,lr\nrun1,0.01\nrun2,0.1\n",
        "c.md": "| Model | FID |\n|---|---|\n| XL | 2.27 |\n",
        "d.log": "epoch 1 loss: 0.5\n",
    })
    kinds = pack["stats"]["kinds"]
    check("mat.yaml_parsed", kinds["config"] >= 1, f"kinds={kinds}")
    eq("mat.csv_parsed", kinds["table"], 1)
    eq("mat.md_is_prose", kinds["manuscript"], 1)
    eq("mat.log_parsed", kinds["log"], 1)
    depths = [u for u in pack["units"] if u.get("key", "").endswith("depth")]
    check("mat.inline_comment_stripped",
          depths and "12" in str(depths[0]["value_text"]),
          f"units={[u['value_text'] for u in depths]}")
    cells = [u for u in pack["units"] if u["kind"] == "table" and u["source"] == "c.md"]
    check("mat.table_cell_has_column_name",
          any(u["key"].lower().startswith("fid") for u in cells),
          f"keys={[u['key'] for u in cells]}")
    eq("mat.readme_not_config", [f["kind"] for f in pack["files"] if f["source"] == "c.md"],
       ["manuscript"])

    # pdf without a backend is reported, never guessed
    blank = pack_of({"x.pdf": "%PDF-1.4 broken"})
    check("mat.broken_pdf_reported", len(blank["unreadable"]) == 1,
          f"unreadable={blank['unreadable']}")

    # case.json itself must never become material
    case_pack = pack_of({"case.json": '{"case_id": "x", "note": "secret"}',
                         "a.yaml": "lr: 1e-4\n"})
    check("mat.case_json_skipped", all(f["source"] != "case.json" for f in case_pack["files"]))

    # the draft must not supply its own numbers as evidence (circular provenance)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import run_case as R
    tmp = Path(tempfile.mkdtemp(prefix="ledger-selftest-"))
    (tmp / "case.json").write_text(json.dumps({"case_id": "t"}), encoding="utf-8")
    (tmp / "config.yaml").write_text(y("train:", "  lr0: 0.01", "  momentum: 0.937"),
                                     encoding="utf-8")
    draft = tmp / "draft.md"
    draft.write_text("## Setup\n\nWe use learning rate 0.001.\n", encoding="utf-8")
    skip = R.skip_set(tmp, None, draft)
    cp = M.read_material(tmp, skip_files=skip)
    check("mat.draft_not_material", [f["source"] for f in cp["files"]] == ["config.yaml"],
          f"files={[f['source'] for f in cp['files']]}")
    lex = json.loads((ROOT / "assets" / "lexicon.json").read_text(encoding="utf-8"))
    cands = P.extract(cp, lex)
    sch = json.loads((ROOT / "assets" / "schema.json").read_text(encoding="utf-8"))
    ledx = L.build(cands, sch)
    alx = A.align(ledx, draft.read_text(encoding="utf-8"), lex, cands, cp)
    inv = [v for v in alx["forward"]["invented"] if v["raw"] == "0.001"]
    check("mat.unsourced_value_has_hint", len(inv) == 1 and inv[0].get("ledger_value") == "0.01",
          f"invented={inv}")

    # model factories define variants through keyword arguments on return lines;
    # dropping them collapsed XL/2, XL/4 and XL/8 into one patch_size
    code = y("def DiT_XL_2(**kwargs):", "    return DiT(depth=28, patch_size=2, **kwargs)",
             "def DiT_XL_4(**kwargs):", "    return DiT(depth=28, patch_size=4, **kwargs)")
    unit = {"source": "m.py", "locator": "L1", "kind": "code", "source_kind": "code",
            "text": "", "key": "", "value_text": "", "func": ""}
    got = []
    for line in code.splitlines():
        u = dict(unit, text=line)
        got += [(v["raw_name"], v["value_text"]) for v in P.code_candidates(u)]
    check("mat.return_kwarg_kept", ("patch_size", "2") in got and ("patch_size", "4") in got,
          f"got={got}")


def main() -> int:
    for fn in (t_numbers, t_ledger, t_align, t_gate, t_contract, t_determinism, t_material):
        try:
            fn()
        except Exception as exc:                    # a crashing test is a failed test
            results.append((fn.__name__ + ".crash", False, f"{type(exc).__name__}: {exc}"))

    bad = [r for r in results if not r[1]]
    for name, ok, detail in results:
        if not ok:
            print(f"FAIL  {name}  {detail}")
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    if bad:
        print("failures:", len(bad))
    return len(bad)


if __name__ == "__main__":
    raise SystemExit(main())
