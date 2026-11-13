#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 B Honey (Mhsbrian/bcd-games)
"""Run the steps of .github/workflows/build-ipa.yml on Linux, one at a time.

The workflow is the reference for what a build of BCD has to do, and it is written for a Mac
runner. This runs its own `run:` scripts, unchanged and in order, inside the Linux build image
(tools/linux/bx), with stand-ins on the PATH for the commands only a Mac has (tools/linux/shims:
xcrun, xcodebuild, sysctl, brew, ...). Nothing is copied out of the workflow, so there is one
place that says how BCD is built, and the first step Linux cannot do is named exactly.

    tools/linux/run-workflow.py list                    every step: number, state, name
    tools/linux/run-workflow.py list --builds           without the "Check ..." steps
    tools/linux/run-workflow.py run --to 120            run the build steps up to number 120
    tools/linux/run-workflow.py run --from 121 --to 140 --checks      the checks in that range too
    tools/linux/run-workflow.py run --only 133 --redo   one step again
    tools/linux/run-workflow.py show 133                a step's script as it would run

A step that succeeded is remembered (out/workflow/state.json, keyed by the script's text) and
skipped the next time, so a run picks up where the last one stopped; --redo forgets that for the
steps selected. The first failing step stops the run unless the workflow marks it
continue-on-error, or --keep-going is given. Each step's output is in out/workflow/logs/.

What is not run: actions (checkout, cache, upload-artifact; the tree and the remembered steps
stand in for the cache, so a "cache-hit" is always false), and by default the "Check ..." steps,
which test the sources rather than build anything. Secrets are empty strings: the steps that sign
and publish need upstream's, and are not for a fork (ANAL-420).
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "build-ipa.yml"
STATE = ROOT / "out" / "workflow"
LOGS = STATE / "logs"
BX = ROOT / "tools" / "linux" / "bx"
SHIMS = ROOT / "tools" / "linux" / "shims"


# Steps that only arrange the Mac runner itself, or publish with upstream's secrets. They are named here,
# with the reason, rather than quietly failing.
NOT_ON_LINUX = {
    "Select newest Xcode": "picks among the Xcodes installed on a Mac; the SDK here is the one tools/linux/bx mounts",
    "Sign for OTA install (private bucket)": "signs and uploads with upstream's secrets; not for a fork",
    "Package Madeira and Madeira2 unsigned IPAs":
        "makes a second app (com.thebcd69.bcd2) as well; the fork packages the one app with tools/linux/package.py",
    "Use public Metal atomics when the compiler needs them (Xcode 27)":
        "changes a shader's source for a newer Metal compiler; the compiled shaders come from a built BCD here",
}


# What has to be in place before a step that would otherwise fetch something built for a Mac.
# Each is run on the host, from the checkout; "{ipa}" is $BCD_UPSTREAM_IPA.
BEFORE = {
    "Install ninja/meson and fetch llvm-mingw": [str(BX), "tools/linux/fetch-llvm-mingw.sh"],
    # Apple's Metal compiler has no Linux build: its stand-in (tools/linux/shims/metal) hands back the four
    # compiled shaders of a Mac build of this version, which this takes out of that build's IPA.
    "Ensure Metal compiler": ["python3", "tools/linux/shaders-from-ipa.py", "{ipa}"],
    # Apple's library, which the public tree does not carry and the workflow stops without.
    "Locate Metal Shader Converter headers": ["python3", "tools/linux/converter-from-ipa.py", "{ipa}"],
}


def load_steps():
    job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["build"]
    return job["steps"]


def load_state():
    try:
        return json.loads((STATE / "state.json").read_text())
    except (OSError, ValueError):
        return {"done": {}, "outputs": {}, "outcome": {}, "env": {}, "path": []}


def save_state(state):
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "state.json").write_text(json.dumps(state, indent=1, sort_keys=True))


def hash_files(*patterns):
    """GitHub's hashFiles: a digest of the matching files, or '' when none matches."""
    digest, found = hashlib.sha256(), False
    for pattern in patterns:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file():
                digest.update(hashlib.sha256(path.read_bytes()).digest())
                found = True
    return digest.hexdigest() if found else ""


class Expressions:
    """The small part of GitHub's expression language this workflow uses."""

    def __init__(self, state, failed):
        self.state, self.failed = state, failed

    def value(self, text):
        text = text.strip()
        m = re.fullmatch(r"steps\.([\w-]+)\.outputs\.([\w-]+)", text)
        if m:
            return self.state["outputs"].get(m.group(1), {}).get(m.group(2), "")
        m = re.fullmatch(r"steps\.([\w-]+)\.outcome", text)
        if m:
            return self.state["outcome"].get(m.group(1), "skipped")
        m = re.fullmatch(r"env\.(\w+)", text)
        if m:
            return self.state["env"].get(m.group(1), os.environ.get(m.group(1), ""))
        if text == "github.workspace":
            return str(ROOT)
        if text == "github.run_number":
            return "0"
        if text == "github.repository":
            return "Mhsbrian/bcd-games"
        if text.startswith("secrets."):
            return ""
        m = re.fullmatch(r"hashFiles\((.*)\)", text, re.S)
        if m:
            return hash_files(*re.findall(r"'([^']*)'", m.group(1)))
        m = re.fullmatch(r"'([^']*)'", text)
        if m:
            return m.group(1)
        if text == "always()":
            return True
        if text == "failure()":
            return self.failed
        if text == "success()":
            return not self.failed
        raise ValueError(f"expression not understood: {text}")

    def test(self, text):
        """An `if:` condition: ||, &&, == and != over the values above."""
        text = str(text).strip()
        if text.startswith("${{") and text.endswith("}}"):
            text = text[3:-2]
        for alternative in text.split("||"):
            if all(self.term(term) for term in alternative.split("&&")):
                return True
        return False

    def term(self, text):
        for op in ("!=", "=="):
            if op in text:
                left, right = text.split(op, 1)
                return (self.value(left) == self.value(right)) == (op == "==")
        value = self.value(text)
        return bool(value) and value != "false"

    def fill(self, text):
        return re.sub(r"\$\{\{(.*?)\}\}", lambda m: str(self.value(m.group(1))), text, flags=re.S)


def is_check(step):
    return str(step.get("name", "")).startswith(("Check ", "Check "))


def key_of(step):
    return hashlib.sha256((step.get("run") or step.get("uses") or "").encode()).hexdigest()[:16]


def read_pairs(path):
    """What a step appended to $GITHUB_ENV or $GITHUB_OUTPUT: NAME=value lines and NAME<<EOF blocks."""
    pairs, lines, i = {}, path.read_text().splitlines() if path.exists() else [], 0
    while i < len(lines):
        line = lines[i]
        m = re.fullmatch(r"([\w-]+)<<(.+)", line)
        if m:
            body = []
            i += 1
            while i < len(lines) and lines[i] != m.group(2):
                body.append(lines[i])
                i += 1
            pairs[m.group(1)] = "\n".join(body)
        elif "=" in line:
            name, _, value = line.partition("=")
            pairs[name] = value
        i += 1
    return pairs


# The whole command, with the lines a trailing backslash continues it onto.
HOST_CHECK = re.compile(r"^[ \t]*python3 tests/host/check-[\w.-]+\.py\b(?:[^\n]*\\\n)*[^\n]*\n?", re.M)


def run_step(number, step, state, expressions, jobs, checks, extra):
    script = expressions.fill(step["run"])
    if not checks:
        # A build step may run a host check of its own before the patch it applies. Those are checks like the
        # "Check ..." steps, several compile and run a piece of the engine on the build machine with macOS
        # headers (mach/mach_time.h, F_GETPATH), and they are left out the same way unless --checks is given.
        script = HOST_CHECK.sub(lambda m: ": # not run on Linux without --checks: " + " ".join(m.group(0).replace("\\\n", " ").split()) + "\n", script)
    LOGS.mkdir(parents=True, exist_ok=True)
    work = STATE / "step"
    work.mkdir(parents=True, exist_ok=True)
    files = {name: work / name for name in ("script.sh", "env", "output", "path", "summary")}
    for name, path in files.items():
        path.write_text(script if name == "script.sh" else "")
    env = dict(state["env"])
    env.update(extra)
    for name, value in (step.get("env") or {}).items():
        env[name] = expressions.fill(str(value))
    env.update(GITHUB_WORKSPACE=str(ROOT), GITHUB_ENV=str(files["env"]), GITHUB_OUTPUT=str(files["output"]),
               GITHUB_PATH=str(files["path"]), GITHUB_STEP_SUMMARY=str(files["summary"]), RUNNER_TEMP=str(STATE / "tmp"),
               RUNNER_OS="Linux", CI="true", BCD_LINUX_BUILD="1", BCD_JOBS=str(jobs),
               PATH=":".join([str(SHIMS)] + state["path"] + ["/opt/cargo/bin", "/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin"]))
    (STATE / "tmp").mkdir(exist_ok=True)
    args = [str(BX), "env"] + [f"{k}={v}" for k, v in env.items()]
    # GitHub runs `bash -e` by default and `bash --noprofile --norc -eo pipefail` for `shell: bash`.
    args += ["bash", "--noprofile", "--norc", "-e"] + (["-o", "pipefail"] if step.get("shell") == "bash" else []) + [str(files["script.sh"])]
    log = LOGS / f"{number:03d}.log"
    started = time.time()
    with log.open("w") as sink:
        sink.write(f"# step {number}: {step.get('name')}\n")
        sink.flush()
        code = subprocess.run(args, cwd=ROOT, stdout=sink, stderr=subprocess.STDOUT).returncode
    state["env"].update(read_pairs(files["env"]))
    if step.get("id"):
        state["outputs"].setdefault(step["id"], {}).update(read_pairs(files["output"]))
    for line in files["path"].read_text().splitlines():
        if line.strip() and line.strip() not in state["path"]:
            state["path"].insert(0, line.strip())
    return code, time.time() - started, log


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["list", "run", "show"])
    ap.add_argument("step", nargs="?", type=int)
    ap.add_argument("--from", dest="first", type=int, default=1)
    ap.add_argument("--to", dest="last", type=int)
    ap.add_argument("--only", type=int, action="append")
    ap.add_argument("--checks", action="store_true", help="run the Check steps too")
    ap.add_argument("--builds", action="store_true", help="list: leave the Check steps out")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--keep-going", action="store_true")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--env", action="append", default=[], metavar="NAME=VALUE",
                    help="a variable for the steps run this time (e.g. MADEIRA_ALLOW_NO_D3D12=1, the build scripts' own switch)")
    a = ap.parse_args()
    steps = load_steps()
    state = load_state()
    extra = dict(pair.split("=", 1) for pair in a.env)
    # The built BCD that stands in for Apple-only tools (shaders, the converter library, the asset catalog):
    # copied once into the checkout, which is all the build image sees, and named to every step by that path.
    reference = os.environ.get("BCD_UPSTREAM_IPA", "")
    if reference and a.action == "run":
        staged = STATE / "upstream.ipa"
        source = Path(reference)
        if not source.is_file():
            sys.exit(f"run-workflow: BCD_UPSTREAM_IPA={reference} is not a file")
        if not staged.exists() or staged.stat().st_size != source.stat().st_size or staged.stat().st_mtime < source.stat().st_mtime:
            STATE.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(source, staged)
        os.environ["BCD_UPSTREAM_IPA"] = str(staged)
        extra.setdefault("BCD_UPSTREAM_IPA", str(staged))
    if a.action == "show":
        step = steps[a.step - 1]
        print(f"# {a.step}: {step.get('name')}\n# if: {step.get('if')}\n# env: {step.get('env')}\n")
        print(Expressions(state, False).fill(step.get("run") or f"uses: {step.get('uses')}"))
        return
    if a.action == "list":
        for number, step in enumerate(steps, 1):
            if a.builds and is_check(step):
                continue
            mark = "done" if state["done"].get(str(number)) == key_of(step) else "uses" if "uses" in step else "    "
            print(f"{number:4d} {mark} {step.get('name', step.get('uses'))}")
        return
    failed, ran = False, 0
    last = a.last or len(steps)
    for number, step in enumerate(steps, 1):
        selected = number in a.only if a.only else a.first <= number <= last
        if not selected:
            continue
        name = step.get("name", step.get("uses"))
        expressions = Expressions(state, failed)
        if "uses" in step:
            if step.get("id"):
                state["outputs"].setdefault(step["id"], {})["cache-hit"] = "false"
                state["outcome"][step["id"]] = "success"
            continue
        if is_check(step) and not a.checks and not a.only:
            continue
        if name in NOT_ON_LINUX:
            print(f"{number:4d} skip  {name}  ({NOT_ON_LINUX[name]})", flush=True)
            continue
        if a.redo:
            state["done"].pop(str(number), None)
        condition = step.get("if")
        if condition is None:
            wanted = not failed
        else:
            wanted = expressions.test(condition)
            if not re.search(r"always\(\)|failure\(\)", str(condition)):
                wanted = wanted and not failed
        if not wanted:
            print(f"{number:4d} skip  {name}  (if: {condition})", flush=True)
            continue
        if state["done"].get(str(number)) == key_of(step):
            if step.get("id"):
                state["outcome"].setdefault(step["id"], "success")
            continue
        print(f"{number:4d} run   {name}", flush=True)
        if name in BEFORE:
            ipa = os.environ.get("BCD_UPSTREAM_IPA", "")
            if "{ipa}" in BEFORE[name] and not ipa:
                sys.exit(f"run-workflow: step {number} needs BCD_UPSTREAM_IPA, an IPA of this version built on a Mac "
                         "(tools/linux/shaders-from-ipa.py says why)")
            command = [ipa if part == "{ipa}" else part for part in BEFORE[name]]
            if subprocess.run(command, cwd=ROOT).returncode:
                sys.exit(f"run-workflow: {' '.join(BEFORE[name])} failed before step {number}")
        code, seconds, log = run_step(number, step, state, expressions, a.jobs, a.checks, extra)
        ran += 1
        if step.get("id"):
            state["outcome"][step["id"]] = "success" if code == 0 else "failure"
        if code == 0:
            state["done"][str(number)] = key_of(step)
            print(f"     ok    {seconds:.0f} s", flush=True)
        else:
            tolerated = bool(step.get("continue-on-error"))
            print(f"     FAIL  exit {code} after {seconds:.0f} s: {log.relative_to(ROOT)}" + ("  (continue-on-error)" if tolerated else ""), flush=True)
            if not tolerated:
                failed = True
                save_state(state)
                if not a.keep_going:
                    sys.exit(1)
                failed = False
        save_state(state)
    save_state(state)
    print(f"run-workflow: {ran} step(s) run" + ("" if not failed else "; stopped on a failure"))


if __name__ == "__main__":
    main()
