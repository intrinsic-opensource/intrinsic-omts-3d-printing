#!/usr/bin/env python3
"""Verifies the local Intrinsic agent knowledge base against the checkouts.

The KB lives in intrinsic-omts (untracked): .github/copilot-instructions.md,
.github/instructions/*.instructions.md and three .agents/skills/intrinsic-*
skills. Sibling repos are expected next to it (intrinsic-core, sdk-examples).

Checks:
  1. Every path mentioned in backticks exists on disk:
     - prefixed paths: intrinsic-core/, intrinsic-omts/, sdk-examples/,
       CORE/, OMTS/, EX/ and @intrinsic-core//pkg:file labels;
     - spans that start with an OMTS top-level dir (configs/, tools/, ...),
       resolved against this repo.
  2. intrinsic-core paths also exist at the commit OMTS pins in MODULE.bazel
     (INTRINSIC_CORE_COMMIT), checked with `git cat-file` (warnings only).
  3. KB SKILL.md frontmatter: `name` == folder, `description` <= 1024 chars.
  4. Drift: repo HEADs and the OMTS core pin vs the `kb-verified` marker in
     .github/copilot-instructions.md.

Usage:
  python3 .agents/skills/intrinsic-cli-and-tutorials/scripts/verify_kb.py [--root /home/berti/gits]
Exit code 1 if a path is missing in the checkout or frontmatter is invalid.
"""

import argparse
import glob
import itertools
import pathlib
import re
import subprocess
import sys

KB_SKILLS = (
    "intrinsic-cli-and-tutorials",
    "intrinsic-hardware-assets",
    "intrinsic-scene-editing",
)
PREFIXES = {
    "intrinsic-core/": "intrinsic-core/",
    "intrinsic-omts/": "intrinsic-omts/",
    "sdk-examples/": "sdk-examples/",
    "CORE/": "intrinsic-core/",
    "OMTS/": "intrinsic-omts/",
    "EX/": "sdk-examples/",
}
PATH_RE = re.compile(
    r"(?<![\w@/.-])(intrinsic-core/|intrinsic-omts/|sdk-examples/|CORE/|OMTS/|EX/)"
    r"([A-Za-z0-9_.{},+*/-]*)"
)
OMTS_REL_RE = re.compile(
    r"^((?:configs|tools|models|src|tests|bazel|docs|third_party|\.agents|\.github)/"
    r"[A-Za-z0-9_.{},+*/-]*)$"
)
LABEL_RE = re.compile(
    r"@intrinsic-core//([A-Za-z0-9_./-]*):([A-Za-z0-9_.-]+\.(?:bzl|textproto|pbtxt|sdf|py|proto))"
)
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
MARKER_RE = re.compile(r"<!--\s*kb-verified:(.*?)-->")
PIN_RE = re.compile(r'INTRINSIC_CORE_COMMIT\s*=\s*"([0-9a-f]{7,40})"')

# Paths the KB mentions on purpose although they don't exist (documented bugs).
KNOWN_INVALID = {
    "intrinsic-core/intrinsic/assets/scene_objects/build_defs/scene_object.bzl",
}
# Exist in the intrinsic-core checkout (20261012.0) but were deleted at the
# OMTS pin; the KB documents them as such.
KNOWN_REMOVED_AT_PIN = {
    "intrinsic-core/intrinsic/assets/build_defs/asset.bzl",
    "intrinsic-core/intrinsic/scene/build_defs/scene_object.bzl",
    "intrinsic-core/intrinsic/tools/inctl/BUILD",
}


def expand_braces(text: str) -> list[str]:
  parts = re.split(r"(\{[^{}]*\})", text)
  choices = [
      p[1:-1].split(",") if p.startswith("{") and p.endswith("}") else [p]
      for p in parts
  ]
  return ["".join(c) for c in itertools.product(*choices)]


def candidate_paths(md_text: str, home: str):
  for span in BACKTICK_RE.findall(md_text):
    for m in LABEL_RE.finditer(span):
      yield f"intrinsic-core/{m.group(1)}/{m.group(2)}", span
    for m in PATH_RE.finditer(span):
      rest = m.group(2).rstrip(".,:;)")
      if rest and "..." not in rest and "<" not in rest:
        yield PREFIXES[m.group(1)] + rest, span
    m = OMTS_REL_RE.match(span.strip())
    if m and "..." not in m.group(1):
      yield f"{home}/{m.group(1).rstrip('.,:;)')}", span


def skip(path: str) -> bool:
  return path in KNOWN_INVALID or any(
      seg.startswith("my_") for seg in path.split("/")
  )


def check_paths(root: pathlib.Path, md_files, home: str):
  missing, core_paths, seen = [], set(), set()
  for md in md_files:
    text = md.read_text(encoding="utf-8")
    for raw, span in candidate_paths(text, home):
      for path in expand_braces(raw):
        if (md, path) in seen or skip(path):
          continue
        seen.add((md, path))
        full = root / path
        ok = bool(glob.glob(str(full))) if "*" in path else full.exists()
        if not ok:
          missing.append(f"{md.relative_to(root)}: missing `{path}`  (from `{span}`)")
        elif path.startswith("intrinsic-core/") and "*" not in path:
          core_paths.add(path)
  return missing, core_paths


def check_at_pin(root: pathlib.Path, pin: str, core_paths) -> list[str]:
  core = root / "intrinsic-core"
  if subprocess.run(["git", "-C", str(core), "cat-file", "-e", f"{pin}^{{commit}}"],
                    capture_output=True).returncode != 0:
    return [f"OMTS core pin {pin} not in local intrinsic-core; run `git -C {core} fetch` to check it."]
  warnings = []
  for path in sorted(core_paths):
    if path in KNOWN_REMOVED_AT_PIN:
      continue
    rel = path[len("intrinsic-core/"):].rstrip("/")
    if subprocess.run(["git", "-C", str(core), "cat-file", "-e", f"{pin}:{rel}"],
                      capture_output=True).returncode != 0:
      warnings.append(f"`{path}` exists in the checkout but NOT at OMTS core pin {pin[:7]}")
  return warnings


def check_frontmatter(skills_dir: pathlib.Path) -> list[str]:
  errors = []
  for name in KB_SKILLS:
    skill_md = skills_dir / name / "SKILL.md"
    if not skill_md.exists():
      errors.append(f"{skill_md}: missing")
      continue
    m = re.match(r"^---\n(.*?)\n---\n", skill_md.read_text(encoding="utf-8"), re.S)
    if not m:
      errors.append(f"{skill_md}: missing YAML frontmatter")
      continue
    fm = m.group(1)
    fm_name = re.search(r"^name:\s*(\S+)\s*$", fm, re.M)
    desc = re.search(r"^description:\s*'(.*)'\s*$", fm, re.M) or re.search(
        r'^description:\s*"(.*)"\s*$', fm, re.M)
    if not fm_name or fm_name.group(1) != name:
      errors.append(f"{skill_md}: name must equal folder '{name}'")
    if not desc:
      errors.append(f"{skill_md}: description missing or not quoted on one line")
    elif len(desc.group(1)) > 1024:
      errors.append(f"{skill_md}: description is {len(desc.group(1))} chars (>1024)")
  return errors


def head(repo: pathlib.Path) -> str:
  try:
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "--short=7", "HEAD"], text=True).strip()
  except Exception:  # pylint: disable=broad-exception-caught
    return "?"


def main() -> int:
  repo = pathlib.Path(__file__).resolve().parents[4]
  parser = argparse.ArgumentParser()
  parser.add_argument("--root", default=str(repo.parent),
                      help="Directory containing the three repos.")
  args = parser.parse_args()
  root = pathlib.Path(args.root).resolve()

  guide = repo / ".github" / "copilot-instructions.md"
  md_files = [guide] if guide.exists() else []
  for name in KB_SKILLS:
    md_files += sorted((repo / ".agents" / "skills" / name).glob("**/*.md"))
  md_files += sorted((repo / ".github" / "instructions").glob("*.instructions.md"))

  missing, core_paths = check_paths(root, md_files, repo.name)
  fm_errors = check_frontmatter(repo / ".agents" / "skills")

  module = (repo / "MODULE.bazel").read_text(encoding="utf-8")
  pin_match = PIN_RE.search(module)
  pin = pin_match.group(1) if pin_match else None
  pin_warnings = check_at_pin(root, pin, core_paths) if pin else [
      "No INTRINSIC_CORE_COMMIT in MODULE.bazel; pin check skipped."]

  marker = MARKER_RE.search(guide.read_text(encoding="utf-8")) if guide.exists() else None
  recorded = dict(kv.split("=", 1) for kv in marker.group(1).split()) if marker else {}
  current = {
      "intrinsic-omts": head(repo),
      "intrinsic-core": head(root / "intrinsic-core"),
      "omts-core-pin": pin[:7] if pin else "?",
  }
  for key, cur in current.items():
    rec = recorded.get(key, "?")
    status = "OK" if rec == cur else "DRIFT: re-verify the KB (copilot-instructions.md > Maintenance)"
    print(f"[{key}] recorded={rec} current={cur} -> {status}")

  print(f"Checked {len(md_files)} files.")
  for line in pin_warnings:
    print("WARN:", line)
  for line in fm_errors + missing:
    print("ERROR:", line)
  if fm_errors or missing:
    print(f"{len(missing)} missing path(s), {len(fm_errors)} frontmatter error(s).")
    return 1
  print("All referenced paths exist; frontmatter OK.")
  return 0


if __name__ == "__main__":
  sys.exit(main())
