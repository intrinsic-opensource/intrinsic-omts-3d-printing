# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

OMTS (Open Machine Tending Solution) is a reference CNC machine-tending app built on Intrinsic Core and its Solution Building Library (SBL) Python SDK. Everything builds with Bazel (Bzlmod; `@intrinsic-core` and `@intrinsic_apis` are fetched via `git_override` in `MODULE.bazel`, pinned by `INTRINSIC_CORE_COMMIT`). Git LFS is required: `*.glb` meshes are LFS-tracked, and without LFS they silently become pointer files.

## Commands

```bash
# Unit tests (hermetic, no cluster/hardware needed)
bazel test //tests/...
bazel test --test_output=errors //tests/unit:test_behaviors   # single target

# Lint / format (mirrors CI: buildifier + ruff)
./tools/lint.sh
./tools/format.sh

# Deploy the solution (default cell is omts; lab cell via flag)
bazel run //:omts_solution -c opt -- --address=localhost:17080
bazel run //:omts_solution -c opt --//:setup=lab_bb_01 -- --address=localhost:17080

# Push configs/<cell>/*.updates.pbtxt to the live world (--reset_sim also syncs Gazebo)
bazel run //tools/world:apply_scene_updates -- --address=localhost:17080 --reset_sim

# Run the machine-tending app against a running deployment
bazel run //src:omts_app -- --address=localhost:17080 --config=configs/omts/app_config.yaml \
  [--num_cycles=N] [--simulation_mode=fast_preview]
```

The pose estimator must be registered (`//tools/pose_estimation:register_using_train_service`, see README §5.3) before `omts_app` can do vision-guided picks. Other operational tools (jogging, gripper, machine I/O, calibration, `inspect_world`) are listed in `tools/README.md`.

CI runs `bazel build --nobuild //...` (analysis only, since full compile does not fit on a GitHub runner) plus `bazel test //tests/...`. Analysis catches stale `@intrinsic-core` labels and missing deps, so run it locally after changing BUILD files or bumping Intrinsic Core.

## Style

- Python 3.11, ruff with **2-space indentation**, line length 80, double quotes (`pyproject.toml`). First-party imports are absolute from the repo root: `from src.core.config import ...`.
- Every new Python module needs a `py_library`/`py_test`/`py_binary` in its package's `BUILD` (using `@intrinsic-core//bazel:python.bzl` macros); tests are `absltest`-based and declared individually in `tests/unit/BUILD`.
- Files carry the Apache 2.0 "Copyright 2026 Intrinsic Innovation LLC" header.

## Architecture

Two separate deliverables:

1. **`//:omts_solution`** (root `BUILD`): an `intrinsic_solution` declaring skills, hardware modules, services (ICON, motion planner, FoundationPose pose estimator, RF-DETR segmentation, Gazebo), scene models from `models/`, and `object_world_updates` from `configs/<cell>/`. The cell is chosen at build time by the `//:setup` string flag (`omts` | `lab_bb_01`), and the BUILD uses `select()` on `:is_lab_bb_01` everywhere. `configs/kr_10/` is a stub that is deliberately not wired in. Some assets are prebuilt bundles downloaded from this repo's GitHub Releases (`bazel/gh_release.bzl`, `imported_asset_bundle`).
2. **`//src:omts_app`** (`src/main.py`): connects over gRPC, loads `configs/<cell>/app_config.yaml` into frozen dataclasses (`src/core/config.py`, missing keys raise `KeyError`), builds hardware adapters and an infeed strategy, assembles **one** `bt.BehaviorTree`, and submits it with a single `solution.executive.run(tree)`.

Layers in `src/`:
- `core/`: domain models, enums, config, infeed strategies (`PerceptionInfeedStrategy` / `GridInfeedStrategy`). **Must not import `intrinsic.*`.**
- `hardware/`: stateless adapters (`UrRobot`, `RobotiqGripper`/`DioGripper`, `DioCncMachine`, `OrbbecVision`) behind abstract interfaces. Each takes `solution` plus its config dataclass and returns SBL `bt.Task`/`bt.Sequence` nodes. Nothing runs at construction time.
- `behaviors/`: five subtree builders (pick → load_machine → machining → unload_machine → return_infeed), composed in `machine_tending_bt.py` and wrapped in `bt.Loop` (`num_cycles` 1, N, or 0 for continuous). `motions.py` holds shared motion primitives (move-to-frame, compliant touchdown via `move_to_contact`, relative `-Z` retract).
- `utils/`: helpers. `dynamic_frame_calculator.py` is special: `load_python_script()` ships its **entire module source** into a `bt.PythonScript` that runs inside the executive. It may therefore only import things available there (stdlib, `intrinsic.*`), never `src.*`.

### Invariants to preserve (see `docs/ARCHITECTURE.md`)

- `AppConfig.machine` is optional (`None` for `lab_bb_01`). Every subtree must omit door/vise/cycle nodes at build time when it is `None`.
- Never disable collision checking globally. Contact and close-proximity segments add targeted `CollisionRule` exclusions (e.g. gripper↔workpiece, workpiece/gripper↔`schunk_egp_64nnb`).
- `update_world` locks the whole world (`lock_the_universe`). Door/vise actuation, which syncs belief-world joints via `update_world`, must run in a `bt.Sequence` before `move_robot`, never in `bt.Parallel`, or you get executive error 18201.
- DIO-based adapters bind ADIO resources only via `resolve_adio_resource()` (it filters on `Icon2AdioPart`).
- `apply_scene_updates` writes the belief world. Gazebo's `sim_world` changes only with `--reset_sim`.

### Configs

`configs/<cell>/app_config.yaml` holds runtime parameters. `*.updates.pbtxt` files are `ObjectWorldUpdates` (attachments, base alignment, named frames like `view`, `machine_approach`, `vise_pre_place`). `*.textproto` files are service configs. `tests/unit/test_world_configs` schema-validates all `.pbtxt`/`.textproto` under `configs/`, so new config files get checked automatically. `//tools/jogging:store_frame` rewrites `scene.updates.pbtxt` in place.

## CI escape hatch

A PR description containing a line `FORCE_SUBMIT=TRUE` skips the Bazel build/test job. Lint still runs. Use it only for changes that cannot affect the build.
