---
name: intrinsic-cli-and-tutorials
description: 'Command reference, tutorial digests and source map for Intrinsic Core, the Open Machine Tending Solution (OMTS) and sdk-examples. Covers inctl (asset install/list/uninstall, asset instance list, service add/delete/state, solution stop, world reset, icon status/enable/clear-faults/list-parts, gpio, skill list), bazel run //:omts_solution deploy flags (--config, --operation_mode=sim), OMTS tools (apply_scene_updates, inspect_world, jog_interactive, move_to_frame, store_frame, control_gripper, control_machine, calibration, pose estimation), k9s namespaces and pods, RViz/Gazebo visualization, setup scripts, and known tutorial errors. Use when you need an exact command and its flags, what a command does and why, which tutorial covers a task, or where a file lives.'
---

# Intrinsic CLI, tutorials and source map

Use this skill to answer "which command, with which flags, and why" without re-reading the tutorials or the inctl Go sources.

## When to use

- You need the exact `inctl`, `bazel run` or OMTS tool invocation for a task.
- You need to know what a tutorial step does and why it works, or whether a tutorial snippet is broken.
- You need the path of a proto, a `.bzl` rule, a tool, a config or an example in `intrinsic-core`, `intrinsic-omts` or `sdk-examples`. Use the source map instead of a repo-wide grep.

## Procedure

1. Look up the command in [command-reference.md](./references/command-reference.md). It is grouped by setup, deploy, assets, world, motion/IO, visualization, k8s and formatting.
2. For a tutorial step's purpose and caveats, read [tutorial-digests.md](./references/tutorial-digests.md). Every tutorial is covered, including the verified mistakes in the tutorials.
3. To find a file, use [source-map.md](./references/source-map.md).
4. Before running anything that moves hardware (`move_to_*`, `jog_interactive`, `icon enable`, `control_gripper`, `control_machine`, or a deploy with `--operation_mode=real`), confirm the solution runs in **sim** (check the Gazebo pod logs, see the command reference; `inctl solution list` does not accept `--address`) or get explicit user consent.
5. After editing knowledge-base files, or after the sibling repos are updated, run the verifier:
   ```bash
   python3 .agents/skills/intrinsic-cli-and-tutorials/scripts/verify_kb.py
   ```
   It checks that every referenced path exists (in the checkout and at the OMTS core pin), validates the SKILL.md frontmatter, and reports drift against the `kb-verified` marker in `.github/copilot-instructions.md`.

## Invariants worth memorizing

- Gateway `localhost:17080`. Zenoh: both `7447` (Istio ingress) and `17447` (direct router LoadBalancer) work on this cluster. Probe with `timeout 2 bash -c '</dev/tcp/127.0.0.1/17447'`, not `ss` (k3s LoadBalancer ports are invisible to it). Pass `--address localhost:17080` everywhere.
- `bazel run //:<solution> -c opt [--config=<cell>] -- --address localhost:17080 --operation_mode=sim`. Bazel flags go before `--`, deployer flags after.
- Install ≠ instantiate: `inctl asset install` registers a type, and `inctl service add <id> --name <n>` creates an instance. A scene-object instance shows up after `inctl world reset`.
- `inctl world reset` restores belief from the initial world and restarts the simulation.
- k9s namespaces:
  - `app-intrinsic-base`: runtime
  - `app-resources`: `rs-icon-0`, `rs-gazebo-simulator-0`, `rs-flowstate-ros-bridge`, ...
  - `skills`

## Related skills

- `intrinsic-scene-editing` covers ObjectWorldUpdates, frames, mounting and persistence.
- `intrinsic-hardware-assets` covers SDF, scene objects, hardware devices, ICON and robot swaps.
- The core API-level skills are tracked in this repo under `.agents/skills/intrinsic-core-*/` (solution building, skill and service authoring, debugging, robot motion).
