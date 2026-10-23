# OMTS cell scene map (intrinsic-omts @ 1548c25, core pin c40e02a)

> **Local change (2026-10-23, uncommitted):** in this checkout the `omts` cell no longer has `cnc_enclosure` or `schunk_egp_64nnb`. They were replaced by `printer` (`models/printer/`, asset `ai.intrinsic.printer`, placed by `configs/omts/printer.updates.pbtxt` at enclosure (−0.57, −0.10, 1.02), yaw +90°). `configs/omts/{cnc_enclosure,schunk}.updates.pbtxt` were deleted.
> - The printer has `bed_frame`, the bed surface center at (0.006, −0.001, 0.0895) in printer coords, ≈ root (−0.569, −0.094, 1.109). It also has `top_frame`.
> - Its GLB is Y-up, so the SDF visual has a roll of +90°.
> - Its collisions are hollow (base slab, top block, 4 posts, spool stack) so parts can rest on the bed.
> - `app_config.yaml` `machine:` still names the CNC and vise. The door and vise world updates are skipped because the objects are missing, but the vise-based place frames and collision exclusions are unchanged.
> - The tables below describe upstream.

All paths are relative to `/home/berti/gits/intrinsic-omts/`.

## How the scene is assembled at deploy time

`BUILD` → `intrinsic_solution(name = "omts_solution", assets=[...], instances=[...], object_world_updates=select({...}))`

1. **assets** = types that get installed: skills, scene objects, hardware devices, services, ML models.
2. **instances** = `intrinsic_asset_instance` targets. Each scene-object or hardware-device instance becomes a **world object named `instance_name`**, or the target `name` if `instance_name` is unset. New objects appear at the parent origin (root) until an update moves them.
3. **object_world_updates** = `.updates.pbtxt` files, applied in order to build the **initial world** (`init_world`). The belief world is a copy of it after deploy or `inctl world reset`.

Cell selection is a Bazel flag:

- `.bazelrc` contains `common --flag_alias=setup=//:setup`, `common:omts --//:setup=omts`, and `common:lab_bb_01 --//:setup=lab_bb_01`.
- Default (no `--config`) = `omts` → `//conditions:default` branches → `configs/omts/*`.
- `--config=lab_bb_01`, or the equivalent `--//:setup=lab_bb_01` used by the README, → `:is_lab_bb_01` branches → `configs/lab_bb_01/*`. The core tutorials deploy with this.
- **Edit the `select()` branch that matches the cell you deploy.** The deploy cell, `omts_app --config=configs/<cell>/app_config.yaml`, and the world tools' `--setup=<cell>` must all match, or frame names differ (e.g. `vise_place` vs `place_vise`).
- `configs/kr_10/` is a stub. It is **not** a `setup` value.

## World objects (instance name → asset ID)

| World object (instance_name) | Asset ID | Kind | Cell |
|---|---|---|---|
| `enclosure` | `ai.intrinsic.omts_enclosure` / `ai.intrinsic.caw_enclosure` (lab) | scene object (static) | both |
| `ur_module` | `ai.intrinsic.ur5e_hardware_module_core` / `ai.intrinsic.ur3e_hardware_module_core` (lab) | hardware device (robot + HWM) | both |
| `icon` | `ai.intrinsic.generic_realtime_control_service` | service (ICON RTCS) | both |
| `gripper` (target `:robotiq_pinch_gripper`) | `ai.intrinsic.robotiq_gripper` | hardware device | both |
| `raw_stock_2x3x5` | `ai.intrinsic.raw_stock_2x3x5` | scene object (dynamic workpiece) | both |
| `orbbec_camera` | `ai.intrinsic.orbbec_gemini_335le` | hardware device (camera) | both |
| `cnc_enclosure` | `ai.intrinsic.cnc_enclosure` | scene object, 1 joint (door) | omts |
| `schunk_egp_64nnb` | `ai.intrinsic.schunk_egp_64nnb` | scene object, 2 prismatic jaws | omts |
| `camera_mount` | `ai.intrinsic.camera_mount` | scene object | omts |
| `charuco_*` | calibration boards | scene objects | both |
| `gazebo_simulator`, `motion_planner_service`, `nvidia_pose_estimator_service`, `train_service`, `calibration_service`, `flowstate_ros_bridge`, `hande_gripper`, `orbbec_gemini_driver` | services | services | both |

`nvidia_pose_estimator_service` (`ai.intrinsic.nvidia_pose_estimator_service`) replaced `inference_service` + `pose_estimator_service` in OMTS #161. `app_config.yaml` sets `vision.perception_service_name: nvidia_pose_estimator_service` and `pose_estimator_id: ai.intrinsic.raw_stock_2x3x5_estimator_text`.

Kinematic attachments:

- `gripper`, `camera_mount` and `orbbec_camera` are reparented onto the final entity (flange link) of `ur_module`.
- `ur_module`, `cnc_enclosure` and `schunk_egp_64nnb` are posed **relative to** `enclosure` / `cnc_enclosure` with `update_transform`. That changes only the pose, not the parent.

## `configs/omts/*.updates.pbtxt` (in `BUILD` deploy order)

| File | What it does |
|---|---|
| `ur_module.limits.updates.pbtxt` | `update_object_joints.joint_application_limits` for all 6 UR5e joints. wrist_3 is limited to [-210°, +220°] for cabling. |
| `ur_module.attachments.updates.pbtxt` | Start joints `[3.14, -1.5707, 1.5707, -1.5707, -1.5707, 3.14]`; flange→`gripper` z = 0.064; `gripper`→`tool_frame` z = 0.155 (`node_a_filter entity_names: "gripper_body"`); reparent `gripper` to `ur_module` final entity; empty `update_kinematic_object_properties` on `ur_module`. |
| `scene.updates.pbtxt` | Global frames on `root`: `vise_pre_place`, `vise_place`, `machine_approach`, `work_view`, `view`, `transit`, `vise_view`, `grasp`, `pre_grasp`; plus the `raw_stock_2x3x5` start pose. **This is the file `store_frame` writes to by default.** |
| `align_robot.updates.pbtxt` | `enclosure` → `ur_module` pose: (0, -0.09, 1.02), identity. |
| `cnc_enclosure.updates.pbtxt` | `enclosure` → `cnc_enclosure` pose (-0.57, -0.10, 1.02, yaw 90°); door joint = 0.4 (open). |
| `schunk.updates.pbtxt` | `cnc_enclosure` → `schunk_egp_64nnb` pose (-0.2, -0.045, 0.05); jaws = [0.01, 0.01] (open). |
| `camera_mount.updates.pbtxt` | flange → `camera_mount` (180° about z: `orientation z:1 w:0`); reparent to `ur_module` final entity; empty `update_kinematic_object_properties`. |
| `orbbec_gemini.updates.pbtxt` | flange → `orbbec_camera` (calibrated pose); reparent to `ur_module` final entity. Written by `//tools/calibration:calibrate_camera --output_updates_file=...` (the README says `calibrate_camera_to_robot`, but the BUILD target is `calibrate_camera`). |
| `raw_stock_in_vise.updates.pbtxt` | Alternate `raw_stock_2x3x5` pose inside the vise. **Not** in the `BUILD` list, but `apply_scene_updates` without `--files` applies it, because it discovers every file in the cell directory. |

`configs/lab_bb_01/` has `ur_module.attachments`, `scene` (frames `view`, `grasp`, `pre_grasp`, `machine_approach`, `pre_place_vise`, `place_vise`), `align_robot` and `orbbec_gemini`. It has no CNC or vise.

### Constraints enforced by `tests/unit/test_world_configs.py`

Run `bazel test //tests/unit:test_world_configs`.

- Every `configs/*/*.updates.pbtxt` must parse as ObjectWorldUpdates and be non-empty.
- The `create_frame` names in `configs/{omts,lab_bb_01}/scene.updates.pbtxt` must **exactly** equal `_EXPECTED_SCENE_FRAMES`. Adding a frame with `store_frame` or by hand requires updating that dict, or putting the frame in a separate updates file.
- `align_robot.updates.pbtxt` is the **only** file that may `update_transform` with `ur_module` as `node_to_update`. `ur_module.attachments.updates.pbtxt` must not duplicate it.
- `ur_module` joint 0 in `ur_module.attachments` must be 3.140 (omts) or 1.5707 (lab_bb_01). The omts wrist_3 limits are fixed.

Frame names consumed by the app are in `configs/<cell>/app_config.yaml` → `frames:` (`view_frame`, `pregrasp_frame`, `grasp_frame`, `transit_frame`, `machine_approach_frame`, `preplace_vise_frame`, `place_vise_frame`) and `robot:` (`arm_part_name: ur_module`, `tool_object_name: gripper`, `tool_frame_name: tool_frame`, `enclosure_object_name: enclosure`). `machine:` holds the CNC door/vise joint values used by `update_world`. **When you rename or add frames, update `app_config.yaml` too.**

`configs/BUILD`:

- `exports_files(glob(["*/*.pbtxt", "*/*.textproto", "*/*.yaml"]))`. **New files in a cell dir are exported automatically**, so a label like `//configs:omts/my_new.updates.pbtxt` just works.
- `filegroup all_world_updates = glob(["*/*.updates.pbtxt"])` is a data dependency of the world tools.

## World tools (`tools/world`, `tools/jogging`)

| Target | Key flags (defaults) | Writes to |
|---|---|---|
| `//tools/world:inspect_world` | `--address` (localhost:17080) | Nothing. Prints objects, joint configs, skills, resources, and flange/tool_frame/view/pre_grasp/grasp poses. |
| `//tools/world:apply_scene_updates` | `--address`; `--setup omts\|lab_bb_01` (omts); `--files` (default: **every** `configs/<setup>/*.updates.pbtxt` in **alphabetical** order, which is not the `BUILD` order and includes `raw_stock_in_vise`); `--reset_sim/--no-reset_sim` (True); `--update_init_world/--no-update_init_world` (False) | `world` (+ `init_world` if flagged); resets Gazebo if simulated. Converts an existing-frame `create_frame` into `update_transform`; skips `update_transform` on missing objects; **skips joint updates on real hardware**. |
| `//tools/world:edit_frames_rviz` | `--address`; `--setup` (omts); `--files` (same discovery); `--frame/--frames <names...>` (limit the markers); `--topic_ns omts_frame_editor`; `--fixed_frame root`; `--marker_scale 0.18`; `--zenoh_endpoint tcp/127.0.0.1:7447`; `--ros_python python3`; `--offline`; `--update_init_world` (**True**); `--apply_on_start` (**False** since OMTS #165); `--reset_sim_on_release` (False) | Drags stream to `world`/`init_world`; **auto-saves the pose into the source `.pbtxt` on mouse release**. |
| `//tools/jogging:store_frame` | positional `name`; `--parent_object root`; `--tool_object gripper`; `--tool_frame tool_frame`; `--scene_updates_file configs/omts/scene.updates.pbtxt` (pass `configs/lab_bb_01/...` for the lab cell) | Current TCP pose → file (create or update entry, keeps comments) + live `world`. Not `init_world`. A **new** frame name breaks `test_world_configs` until `_EXPECTED_SCENE_FRAMES` is updated. |
| `//tools/jogging:store_joint_config` | positional `name`; `--robot_name ur_module` | Live `world` + `init_world` named joint config. **No file**, so it is lost on redeploy. |
| `//tools/jogging:move_to_frame` | `--frame`; `--parent_object root`; `--motion_type ANY\|LINEAR\|JOINT`; `--arm_part_name ur_module`; `--tool_object_name gripper`; `--tool_frame_name tool_frame`; `--allow_tool_z_rotation` | Moves the robot. Sim only unless the user confirms. |
| `//tools/jogging:move_to_joint` | positional target or `--joints ...` / `--name`; `--robot_name ur_module` | Moves the robot. |
| `//tools/jogging:jog_interactive` | `--host localhost --port 17080 --instance icon` | ICON joint jogging (±0.01 rad per arrow key). |
| `//tools/calibration:calibrate_camera` | `--camera orbbec_camera --output_updates_file configs/omts/orbbec_gemini.updates.pbtxt` | Updates `world` + writes the camera mount pbtxt. |
| `//tools/machine:control_machine` | `--action open_door\|close_door\|open_vise\|close_vise\|trigger_cycle\|wait_cycle` | DIO + `update_world` joint sync. |

Path resolution: tools resolve relative `--files` against `BUILD_WORKING_DIRECTORY`, then `BUILD_WORKSPACE_DIRECTORY`, then runfiles (`src/utils/world_utils.py:find_file`). Run them from the repo root, or pass absolute paths such as `/tmp/x.updates.pbtxt`.

## Execution-time scene changes in the app (`src/`)

- `src/hardware/machine.py` `DioCncMachine` appends an `update_world` skill task with `ObjectWorldUpdate(update_object_joints=...)` after each door/vise DIO command, so collision checking matches reality.
- `src/hardware/robot.py` uses `attach_object_to_robot` (`gripper_entity` = tool object `gripper`, `object_entity` = workpiece) and `detach_object` when grasping or releasing. This relies on the core pin c40e02a, where a gripper reference attaches to the gripper's base entity. With core 20261012.0 the same call failed with `"gripper" has multiple final entities`, and the workaround was to pass the arm (`ur_module`).
- `src/hardware/vision.py` uses a `bt.PythonScript` that updates the `grasp`/`pre_grasp` frames from the pose estimate.

## Patching core assets from OMTS

OMTS builds `intrinsic-core` from a pinned **commit**. In `MODULE.bazel`: `INTRINSIC_CORE_COMMIT = "c40e02a…"`, plus `git_override(module_name="intrinsic-core", commit=INTRINSIC_CORE_COMMIT, remote="https://github.com/intrinsic-ai/intrinsic-core.git", patches=["//bazel/patches:robotiq_hande_finger_offset.patch"], patch_strip=1)`. `intrinsic_apis` comes from the same commit's archive. The local `../intrinsic-core` checkout (a3bd446 = 20261012.0) is older. Read pinned files with `git -C ../intrinsic-core show c40e02a:<path>`.

- **Editing `../intrinsic-core` does not change OMTS builds.** To change a core-provided part, add a `-p1` diff under `bazel/patches/`, list it in `bazel/patches/BUILD` `exports_files`, and append it to the `git_override` `patches=[...]`. Other files in `bazel/patches/` patch other modules.
- The existing patch is a real example: it adds `<pose>±0.005 0 0 ...</pose>` to the Robotiq Hand-E finger links in `intrinsic_control/intrinsic/models/assets/standard_tooling/robotiq_hande/robotiq_hande/robotiq_hande.sdf`.
- Alternatively, temporarily use `local_path_override(module_name="intrinsic-core", path="../intrinsic-core")`. That builds whatever is checked out there, which is currently older than the pin, and needs the git-lfs assets pulled.
