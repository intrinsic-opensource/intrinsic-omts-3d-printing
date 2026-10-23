# Local agent guide: intrinsic-omts + intrinsic-core + sdk-examples

This is a personal knowledge base. It is untracked and ignored via `.gitignore`. It complements the upstream, tracked [AGENTS.md](../AGENTS.md), which has the generic Intrinsic Core rules and the `.agents/skills/intrinsic-core-*` skills.

**Read the knowledge base below before searching the repos.** It is source-verified and records where the tutorials are wrong.

<!-- kb-verified: intrinsic-omts=1548c25 intrinsic-core=a3bd446 omts-core-pin=c40e02a -->

## Workspace: three sibling checkouts in `/home/berti/gits/`

| Repo | Role | Verified at |
|---|---|---|
| `intrinsic-omts/` (**this repo**, working dir) | Open Machine Tending Solution. `BUILD` (`intrinsic_solution`), `configs/<cell>/` (scene updates, ICON/HWM configs, `app_config.yaml`), `models/` (scene objects), `tools/` (world, jogging, calibration CLIs), `src/` (SBL app), `tests/`. | commit 1548c25 |
| `intrinsic-core/` (sibling; read for docs and source) | Intrinsic Core: runtime, `inctl`, SDK (`intrinsic_sdk/`), protos (`intrinsic_apis/`), ICON, perception, and tutorials (`developer_resources/`). | checkout a3bd446, which is tag 20261012.0 (tutorials, release `inctl`/runtime). **OMTS builds core at c40e02a** (`MODULE.bazel` `git_override`), 190 commits newer. Read the exact pinned file with `git -C ../intrinsic-core show c40e02a:<path>`. |
| `sdk-examples/` (sibling) | Flowstate SDK examples (`@ai_intrinsic_sdks`): skills, services, SBL notebooks (`notebooks/003_world.ipynb`, `notebooks/011_scene_object_import.ipynb`, `skills/use_world/`). | main 436163b |

Tutorials assume `~/intrinsic-omts` and `~/intrinsic-core`. Here those are `/home/berti/gits/intrinsic-omts` and `/home/berti/gits/intrinsic-core`.

## Knowledge base (load on demand)

| Need | Load |
|---|---|
| Change the scene: frames, transforms, robot base, mount tools, joints/limits, collisions, persistence, reset | `.agents/skills/intrinsic-scene-editing/SKILL.md` |
| Create or edit hardware parts: SDF, meshes, scene objects, hardware devices, grippers, cameras, robots/ICON, swaps | `.agents/skills/intrinsic-hardware-assets/SKILL.md` |
| Exact commands and flags, tutorial step explanations, where files live | `.agents/skills/intrinsic-cli-and-tutorials/SKILL.md` (+ `references/source-map.md`) |
| Proto-level ObjectWorldUpdates fields and templates | `.agents/skills/intrinsic-scene-editing/references/object-world-updates.md` |
| Bazel rules, load labels and manifests | `.agents/skills/intrinsic-hardware-assets/references/bazel-asset-rules.md` |
| Behavior trees, skills, services, low-level gRPC APIs, debugging | Upstream `.agents/skills/intrinsic-core-*/SKILL.md` (tracked copies of the core skills) |

File-scoped rules in `.github/instructions/` attach automatically for `*.updates.pbtxt`, `*.sdf`, and `models/**` or manifest files.

## Golden rules

1. **Safety.** Never command real hardware without explicit user confirmation. That includes `--operation_mode=real`, `inctl icon enable` on a real cell, `move_to_*`, `jog_interactive`, and the gripper and machine tools. `BUILD` has `default_operation_mode = "real"`, so **always pass `--operation_mode=sim`**.
2. **Addressing.**
   - The gateway is `localhost:17080`. Pass `--address localhost:17080` to every `inctl` and OMTS tool.
   - Zenoh/ROS 2: on this cluster **both** `7447` (via the Istio ingress) and `17447` (direct `zenoh-router-host` LoadBalancer) reach the same router (verified 2026-10-23). **`ss -ltn` does not show them** (k3s svclb uses iptables); probe with `timeout 2 bash -c '</dev/tcp/127.0.0.1/17447'` or `kubectl get svc -A | grep 7447`.
   - Confirm what is deployed with `inctl asset instance list --address localhost:17080` and `kubectl get pods -n app-resources`. **`inctl solution list`/`get` are Flowstate-cloud only (no `--address` flag, so they error with `unknown flag: --address`).**
   - Sim vs real: check `kubectl logs -n app-resources rs-gazebo-simulator-0 --tail=20`. `hardware_module_launcher` lines mean sim; `noop.go ... Server is now listening` means real.
3. **Three worlds.**
   - `init_world` is built at deploy from instances plus `object_world_updates`.
   - `world` is the belief world, live, and is what RViz shows.
   - `sim_world` is Gazebo.

   Live edits only touch `world`. `inctl world reset` copies init → belief, then restarts the sim. **Permanent = edit the source (`configs/<cell>/*.updates.pbtxt`, `BUILD`, SDF) and redeploy.**
4. **One name per thing.** `intrinsic_asset_instance.instance_name` = world object name = `object_name` in updates = ICON `module_name`/`hardware_resource_name` = `app_config.yaml` names. Rename all of them together (`grep -rn`).
5. **Units.** Meters and radians. Quaternions are `x y z w`, and you must write `w` explicitly.
6. **Install ≠ instance.** `inctl asset install` registers a type. `inctl service add <id> --name <n>` creates an instance (also for scene objects). Then run `inctl world reset`.
7. **Trust order.** Source at the OMTS core pin > working OMTS configs > tutorials. Never invent asset IDs or Bazel targets.
8. **Bazel.**
   - Never `sudo bazel`.
   - Core comes from `git_override(commit = c40e02a, patches = ["//bazel/patches:robotiq_hande_finger_offset.patch"])`. Editing `../intrinsic-core` does **not** affect OMTS. Patch via `bazel/patches/`.
   - Use `@intrinsic-core//intrinsic_sdk/...` load labels. The legacy forwarders `//intrinsic/assets/build_defs:asset.bzl` and `//intrinsic/scene/build_defs:scene_object.bzl` are **deleted at the pin**.
9. **Match the cell.**
   - `--config=lab_bb_01` (≡ `--//:setup=lab_bb_01`) selects the `:is_lab_bb_01` `select()` branches and `configs/lab_bb_01/`. The default is `omts`.
   - Use the same cell for `omts_app --config=configs/<cell>/app_config.yaml` and the world tools' `--setup=<cell>`.
10. **Tests guard the scene.** Run `bazel test //tests/unit:test_world_configs`. It checks that:
    - every `configs/*/*.updates.pbtxt` parses and is non-empty
    - the `create_frame` names in each `scene.updates.pbtxt` **exactly** match `_EXPECTED_SCENE_FRAMES` in `tests/unit/test_world_configs.py` (update it when adding or removing frames)
    - only `align_robot.updates.pbtxt` sets the `enclosure → ur_module` base transform
    - joint 0 values and the UR5e limits match

## Build, test, lint (this repo)

```bash
bazel build --nobuild //...            # analysis only
bazel test //tests/...                 # unit tests; avoid bare //... (builds solution images)
./tools/format.sh && ./tools/lint.sh   # buildifier + ruff (CI checks)
bazel run //:omts_solution -c opt [--config=lab_bb_01] -- --address=localhost:17080 --operation_mode=sim
bazel run //src:omts_app -- --address=localhost:17080 --config=configs/<cell>/app_config.yaml
```

## Verified tutorial and doc errors (do not copy these)

| Snippet | Correct |
|---|---|
| `load("@intrinsic-core//intrinsic/assets/scene_objects/build_defs:scene_object.bzl", ...)` (import_new_part, convert_3d_models) | `@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl` |
| `load("@intrinsic-core//intrinsic/assets/build_defs:asset.bzl", "intrinsic_asset_instance")` (robot_bringup, kuka_rsi_setup, universal_robots_setup) | Deleted at the OMTS pin c40e02a. Use `@intrinsic-core//intrinsic_sdk/intrinsic/assets/build_defs:asset.bzl`. |
| `intrinsic_asset(...)` (custom_asset_creation_hardware) | No such rule. Use `intrinsic_scene_object`, or `intrinsic_hardware_device` + `intrinsic_service`. |
| `intrinsic_proto.assets.AssetManifest` with `type: HARDWARE_DEVICE` | `SceneObjectManifest` / `HardwareDeviceManifest` (metadata + graph) |
| SDF `<frame name="tool_frame">` without attributes | Add `intrinsic:create_entity="true"` and `xmlns:intrinsic="https://intrinsic.ai/"`, or the frame is dropped. |
| `intrinsic_asset_instance(config=":<Any config>.textproto")` | `service_config = ...` (`config` is a full InstanceConfig) |
| Asset `ai.intrinsic.wsg32_gripper_strauss` | Does not exist. |
| `bazel run //tests:progressive_skills_demo` (custom_asset_creation_software) | No such target in sdk-examples. |
| `UpdateObjectJointsRequest` comment "degrees" | Radians (Python client and every OMTS config). |
| `@intrinsic-core//intrinsic/tools/inctl:inctl_external` (robot_bringup `env.sh`) | `@intrinsic-core//intrinsic_sdk/intrinsic/tools/inctl:inctl_external` |
| `//tools/calibration:calibrate_camera_to_robot` (`tools/README.md`) | `//tools/calibration:calibrate_camera` |
| `inctl solution list --address localhost:17080` (custom_hardware_modules) | `unknown flag: --address`. `solution list` is Flowstate-only. Use `inctl asset instance list --address localhost:17080` and the Gazebo pod logs. |
| `//tools/pose_estimation:register_using_train_service` (visualize_the_solution) | Removed in OMTS #161. Use `bazel run @intrinsic-core//intrinsic_perception/intrinsic/perception/service/ioc_train_service/tools:register_using_ioc_train_service -- ... --pose_estimator_id=ai.intrinsic.raw_stock_2x3x5_estimator_text --text_prompt="cuboid"` (README §4.3). |

## Maintenance

- After editing knowledge-base files, or when any of the three repos moves (`git pull`, re-clone, or a `MODULE.bazel` pin bump), run:
  ```bash
  python3 .agents/skills/intrinsic-cli-and-tutorials/scripts/verify_kb.py
  ```
  It checks every referenced path (in the checkout and at the OMTS core pin), validates the skill frontmatter, and reports drift against the `kb-verified` comment above.
- On drift:
  1. Re-check the load labels, asset IDs, tool flags (`grep add_argument tools/**/*.py`), `BUILD` instances, and the error table. Use `git -C <repo> diff --stat <old>..<new>` to scope the check.
  2. Update the facts.
  3. Bump the `kb-verified` comment and the "Verified at" column.
- Add new verified gotchas to the relevant SKILL.md "Gotchas" section.
