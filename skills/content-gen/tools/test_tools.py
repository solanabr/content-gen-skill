#!/usr/bin/env python3
"""
test_tools.py — run every content-gen tool's selftest. Exit non-zero on any failure.
Pure stdlib; no network. Mirrors writer-style/tools/test_tools.py.

    python test_tools.py
    python test_tools.py --list      # what is registered, and what each one's entry point is

WHY THIS FILE IS SHAPED LIKE THIS. A hand-maintained import list is how tools go orphan:
verify_blocks.py (1366 lines, 31 selftests) and dedash.py both had working selftests that
nothing ran, because nobody remembered to add the import. So the registry is now
DISCOVERED, not typed:

  * every module in tools/ that exposes `selftest()` (or a private `_selftest()`) is run;
  * REGISTERED names the tools we know about, and fixes their order;
  * a tool that exists but is NOT in REGISTERED is a HARD FAILURE, not a silent pass.

That last rule is the whole point. Adding a tool with a selftest and forgetting to register
it now breaks the build immediately, instead of shipping an unrun test for months.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Ordered, and the source of truth for "we know this tool exists". Cheap ones first so a
# broken import surfaces before a slow compile does.
#
# A name here that has no file yet is reported as "not present on this branch" and skipped, so
# this list may run AHEAD of the tools it names. That is deliberate: the entry waits for the
# branch instead of the branch waiting for someone to remember the entry, which is precisely
# how five working selftests (verify_blocks, dedash, assemble_manifest, quiz_metrics,
# quiz_layout) came to be run by nothing.
REGISTERED = [
    "course_lib",
    "pin_refresh",
    "validate_course",
    "scaffold_course",
    "verify_code",
    "verify_blocks",
    "verify_challenges",
    "render_visuals",
    "academy_export",
    "assemble_manifest",     # branch: feat/lift-wave2-into-skill
    "quiz_edit",             # branch: fix/quiz-path-hardening (renamed from quiz_balance)
    "quiz_metrics",          # branch: fix/quiz-path-hardening
    "quiz_layout",           # branch: fix/quiz-path-hardening
    "quiz_balance",          # pre-rename name; drop this line once quiz_edit lands
    "dedash",
    "ci",
]

# Modules in tools/ that legitimately have no selftest of their own.
NO_SELFTEST_OK = {"test_tools"}


def _modules_on_disk() -> list[str]:
    return sorted(p.stem for p in HERE.glob("*.py")
                  if not p.stem.startswith("_") and p.stem not in NO_SELFTEST_OK)


def _entry(mod):
    """A tool's selftest, whatever it chose to call it.

    `_selftest` is accepted so a private name still RUNS -- an unrun test is worse than an
    inelegant one -- but --list reports it so it can be renamed.
    """
    return getattr(mod, "selftest", None) or getattr(mod, "_selftest", None)


def resolve():
    """(name, module_or_None, entry_or_None, note) for every registered + discovered tool."""
    on_disk = set(_modules_on_disk())
    out, seen = [], set()
    for name in REGISTERED + sorted(on_disk - set(REGISTERED)):
        if name in seen:
            continue
        seen.add(name)
        if name not in on_disk:
            # Registered but absent: a tool that lives on another branch yet. Reported, never
            # a crash, so this file merges cleanly with branches that add tools.
            out.append((name, None, None, "not present on this branch"))
            continue
        try:
            mod = importlib.import_module(name)
        except Exception as e:                                     # noqa: BLE001
            out.append((name, None, None, f"IMPORT ERROR: {type(e).__name__}: {e}"))
            continue
        fn = _entry(mod)
        note = ""
        if fn is None:
            note = "no selftest"
        elif getattr(mod, "selftest", None) is None:
            note = "private _selftest (rename to selftest)"
        out.append((name, mod, fn, note))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="run every content-gen tool's selftest")
    ap.add_argument("--list", action="store_true", help="show the registry and exit")
    a = ap.parse_args(argv)

    rows = resolve()
    if a.list:
        for name, _mod, fn, note in rows:
            state = "ok" if fn else "-"
            print(f"{name:22} {state:3} {note}")
        return 0

    rc = 0
    unregistered, no_test, broken = [], [], []
    for name, mod, fn, note in rows:
        if note == "not present on this branch":
            print(f"\n===== {name} =====\nskip - {note}")
            continue
        if note.startswith("IMPORT ERROR"):
            print(f"\n===== {name} =====\nFAIL - {note}")
            broken.append(name)
            rc = 1
            continue
        if name not in REGISTERED and fn is not None:
            unregistered.append(name)
        if fn is None:
            no_test.append(name)
            continue
        print(f"\n===== {name} ====={('  [' + note + ']') if note else ''}")
        rc |= fn()

    if unregistered:
        print(f"\nFAIL - unregistered tool(s) with selftests: {', '.join(unregistered)}")
        print("       Add them to REGISTERED in tools/test_tools.py. A tool whose selftest "
              "nothing runs is how verify_blocks.py stayed orphaned.")
        rc = 1
    if no_test:
        print(f"\nnote - no selftest: {', '.join(no_test)}")

    print("\n" + ("ALL TOOL SELFTESTS PASSED" if rc == 0 else "SOME SELFTESTS FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
