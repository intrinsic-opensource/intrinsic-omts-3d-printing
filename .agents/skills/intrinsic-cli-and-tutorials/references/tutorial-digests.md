# Tutorial digests (intrinsic-core `developer_resources/`)

The tutorials were read at 20261012.0 (a3bd446, the local checkout). The OMTS core pin c40e02a only changes `getting_started.md` (the `setup_nvidia.sh` step moved before the runtime deploy) and `visualize_the_robot.md` (Zenoh port 17447). Where current OMTS (1548c25) no longer matches a tutorial, it is flagged as ⚠️ OMTS drift.

Each entry gives the purpose, the steps (with the commands in [command-reference.md](./command-reference.md)), **why it works**, and verified caveats. Tutorials live in `intrinsic-core/developer_resources/learn/tutorials/`. Read the original only when you need screenshots or prose.

## 1. getting_started.md: install runtime, build and deploy OMTS

- **Steps:**
  1. git-lfs + gh
  2. clone core@`20261012.0` and the latest OMTS release
  3. `setup_k3s.sh`
  4. deploy `intrinsic-base` from the release tar
  5. install `inctl`
  6. (optional) `setup_nvidia.sh`
  7. Bazelisk + the libxml2 symlink
  8. `bazel run //:omts_solution --config=lab_bb_01 -- --address localhost:17080 --operation_mode=sim`
- **Why:** Intrinsic Core is a set of k8s workloads ("intrinsic-base") on local k3s. A *solution* is a Bazel-built `LocalSolution` proto plus asset bundles. `bazel run` executes `solution_update`, which uploads images and geometry to the cluster CAS, calls the DeployService, and waits for readiness.
- **Caveats:**
  - Ubuntu 26.04, x86-64 only.
  - Intel CPU for real-time; 32 GB RAM or more.
  - A GPU is needed for perception.
  - The first build takes about 50 minutes.
  - `/tmp` quota issues are fixed with `TMPDIR=~/tmp`.
  - An IP change breaks the cluster; reinstall k3s.
  - ⚠️ OMTS drift: current OMTS builds core from commit c40e02a (`git_override`), not the 20261012.0 release.

## 2. visualize_the_robot.md: RViz (belief) and Gazebo (sim)

- **Why two views:** RViz renders the **belief world** that the ROS bridge (`rs-flowstate-ros-bridge`) publishes from the ObjectWorld service (`/workcell_markers`, `/tf`) over Zenoh (`:7447` at 20261012.0; the c40e02a version of this tutorial says `:17447`, so check which port listens). Gazebo shows the **physics simulation** (`rs-gazebo-simulator-0`, partition `intrinsic_sim`). They diverge on bad pose estimates, on disconnects, or when physics moves parts.
- **Caveats:**
  - MarkerArray durability must be **Transient Local**.
  - No TF or meshes means you must restart the bridge pod.
  - The Gazebo GUI needs the meshes copied out of the `asset_sim` process (`/mnt/gzserver-meshes`).
  - A "noop" simulator in the logs means the solution was deployed in real mode.

## 3. jog_the_robot.md: ICON sanity check and joint jogging

- **Steps:**
  1. `inctl asset instances list` to find the ICON instance (`icon`).
  2. `inctl icon status --instance_name icon` should show ENABLED.
  3. `bazel run //tools/jogging:jog_interactive -- --host=localhost --port=17080 --instance=icon`.
- **Why:** jog_interactive opens an ICON session on part `arm` and streams `joint_jogging` goal updates with a deadman timeout.
- **Caveats:**
  - `Unimplemented` means a wrong instance name, or real mode on a non-RT PC (`rs-icon-0` Pending).
  - FAULTED after a Gazebo restart: run `clear-faults`.
  - `Part 'arm' is already in use`: disable then enable.
  - `Goal violates Part limits`: you jogged too far.

## 4. visualize_the_solution.md: run the OMTS process

- **Steps:**
  1. `register_using_train_service` (pose estimator for `ai.intrinsic.raw_stock_2x3x5`)
  2. `bazel run //src:omts_app -- --address=localhost:17080 --config=configs/lab_bb_01/app_config.yaml`
- ⚠️ **OMTS drift (#161):** `//tools/pose_estimation:register_using_train_service` no longer exists. OMTS now uses `nvidia_pose_estimator_service` and the estimator `ai.intrinsic.raw_stock_2x3x5_estimator_text`, registered with `bazel run @intrinsic-core//intrinsic_perception/intrinsic/perception/service/ioc_train_service/tools:register_using_ioc_train_service -- ... --text_prompt="cuboid"` (README §4.3, [command-reference.md](./command-reference.md)). Model setup follows the core `nvidia_pose_estimator` README at the pin.
- **Why:** `omts_app` composes an SBL behavior tree: perception → compliant touchdown (`move_to_contact`) → motion planning around the known geometry. The executive runs the skills against the belief world.
- **Caveats:**
  - `dio_set_output ... no healthy upstream` means the solution was deployed real without RT setup.
  - `requested id ..._estimator not found` means you must re-register after a restart. The current ID ends in `_estimator_text`.
  - `0 detections` happens when the part fell out of view; restart the solution.
  - A long pause followed by NOT_FOUND was an inference-service race in the old pipeline (delete `rs-inference-service-0`). With #161, restart the pose-estimator pod instead.
  - A long pause followed by UNAVAILABLE means there is no GPU or `setup_nvidia.sh` was not run.
  - A collision with `enclosure.base_link` means the part fell from the vise; run `inctl world reset`.
  - `Frame "pre_place_vise" does not exist` means the deploy config and app config are mismatched.

## 5. cell_customization.md: ObjectWorldUpdates (SCENE EDITING)

- **Steps:**
  1. **Live edit:** write `/tmp/capture_frame.updates.pbtxt` (`create_frame` "capture" on root at (0.3, 0, 1.2)). Apply it with `apply_scene_updates --files`, view it in RViz TF, and undo with `inctl world reset`.
  2. **Relocate the robot:** write `/tmp/relocate_robot.updates.pbtxt` (`update_transform` root→`ur_module`, `node_to_update` `ur_module`, (0.5, -0.3, 1.0), q = (0, 0, -0.707, 0.707)). Run `inspect_world` before and after; the flange moves with the base.
  3. **Permanent:**
     1. `cp /tmp/relocate_robot.updates.pbtxt .`
     2. Append `":relocate_robot.updates.pbtxt"` to the `:is_lab_bb_01` list of `omts_solution.object_world_updates`.
     3. Redeploy with `--config=lab_bb_01`, then `inctl world reset`.
     4. Clean up with `rm` + `git checkout BUILD` + redeploy + reset.
- **Why:** At deploy, Intrinsic records an **initial world** = instances + `object_world_updates` applied in order. `inctl world reset` copies initial → belief and restarts the simulation. Live updates touch only belief (and Gazebo via `--reset_sim`), so they vanish on reset. Kinematics and planning use the belief world immediately.
- **Caveats:**
  - The tutorial adds to the lab_bb_01 branch. With the default config you must edit the `//conditions:default` branch instead.
  - A containerd.sock error on redeploy means deleting the `artifacts-deployment-*` pod.
  - The proto link in the tutorial points to `intrinsic-ai/sdk`. The local copy is `intrinsic-core/intrinsic_sdk/intrinsic/world/proto/object_world_updates.proto`.
  - ⚠️ OMTS drift:
    - A file that moves `ur_module` other than `align_robot.updates.pbtxt` now fails `bazel test //tests/unit:test_world_configs`. That's fine for a tutorial run, but keep it in mind for real edits.
    - `apply_scene_updates` gained `--setup`. Without `--files` it applies the whole cell directory.

## 6. swap_assets.md: swap a skill (CLI) and a robot (BUILD)

- **Part 1:**
  1. `inctl skill list`
  2. `inctl asset uninstall ai.intrinsic.clear_motion_planner_service_cache`
  3. `bazel build @intrinsic-core//intrinsic/skills/examples:adder_skill`
  4. `inctl asset install "$(bazel --quiet cquery --output=files ...)"`
  5. Check the logs with `k9s -n skills -c services`.

  Skills have no instances; they are parameterized in processes. Runtime changes are undone by redeploy.
- **Part 2 (UR3e → KUKA KR10):** swap the HWM asset and instance, copy `kuka_rsi_default_config.textproto`, point ICON to `configs/kr_10/icon_config.textproto`, `sed` `ur_module` → `kuka_rsi_hal_module` in `configs/lab_bb_01/*.updates.pbtxt`, then `inctl solution stop` and redeploy.
- **Why:** a robot = an HWM hardware device (service + scene object) + the RTCS (ICON) config referencing the HWM by **instance name**, plus world updates referencing the **object name**. All three must agree, and the control frequencies must match (UR 500 Hz, KUKA 250 Hz).
- **Caveats:** the error table is in `intrinsic-hardware-assets/references/hardware-devices-and-icon.md`. RViz needs MarkerArray, not RobotModel. Reopen the Gazebo GUI after a swap.

## 7. import_new_part.md: new SceneObject (HARDWARE PART)

- **Steps:**
  1. `mkdir models/raw_stock_logo`
  2. Copy the glb from `intrinsic-core/intrinsic/models/assets/imts/raw_stock/raw_stock_green_logo.glb`.
  3. Write the manifest (`SceneObjectManifest`), the SDF (mass, inertia, glb visual, box collision 0.05×0.075×0.05) and the BUILD (`sdf_scene_object` + `intrinsic_scene_object`).
  4. `bazel build //models/raw_stock_logo:raw_stock_logo`
  5. `inctl asset install bazel-bin/models/raw_stock_logo/raw_stock_logo.bundle.tar`
  6. `inctl service add ai.intrinsic.raw_stock_logo --name raw_stock_logo`
  7. `inctl world reset`
  8. `inctl asset instance list`
- **Why:** an asset type is installed first, and then an **instance** (`service add`) adds it to the initial world. Reset copies it into belief and sim. Multiple instances of one asset are allowed (bin picking).
- **Caveats:**
  - ⚠️ **The BUILD in the tutorial uses `@intrinsic-core//intrinsic/assets/scene_objects/build_defs:scene_object.bzl`, which does not exist.** Use `@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl`, as every `intrinsic-omts/models/*/BUILD` does.
  - The part spawns at the origin; move it with ObjectWorldUpdates.
  - Static parts need `<static>true</static>` or `simulation_component.is_static`.
  - To persist, add it to `assets` + `instances` in the solution BUILD.

## 8. custom_asset_creation_software.md: Python skills

- **Steps (in sdk-examples):**
  1. `bazel test //skills/say_skill:say_skill_py_test`
  2. `bazel build //skills/say_skill:say_skill_py_image`
  3. `inctl skill install bazel-bin/skills/say_skill/say_skill_py_image.bundle.tar --address=localhost:17080`
  4. Same for `validate_pose`, which queries ObjectWorld transforms. Verify with `inctl skill list`, `kubectl get pods -n skills`, and `kubectl logs -n skills <pod>`.
- **Why:** a skill bundle is a container image + manifest + proto descriptors. Install it and the executive can call it. Skills are **stateless** (a new instance per call), so heavy state belongs in services.
- **Caveats:**
  - `//tests:progressive_skills_demo` (Module 3) **does not exist** in `sdk-examples/tests/BUILD`.
  - sdk-examples builds against `@ai_intrinsic_sdks` (the `intrinsic-ai/sdk` main branch), not `@intrinsic-core`.

## 9. custom_asset_creation_hardware.md: Weiss GRIPKIT/WSG32 gripper (HARDWARE PART)

- **Content:**
  - SDF with `gripper_base`, 2 prismatic fingers (0–0.034 m) and `tool_frame` at z 0.125.
  - A mount file (`ur_module.attachments.updates.pbtxt`): flange→gripper, reparent with `include_final_entity`, and the `tool_frame` transform.
  - Actuation option 1, DIO: `WeissGripkitDio` SBL adapter using `dio_set_output` (open pin 0, close pin 1) and `dio_wait_for_input` (gripped = in 0).
  - Actuation option 2, native driver: a `PinchGripperPart` config with `pinch_gripper_driver_name: "Wsg32Gripper"` at 192.168.1.20:50042, plus the `control_pinch_gripper` skill.
- **Why:** hardware has two layers. **(a) the spatial model** (SDF scene object + mount ObjectWorldUpdates) drives collision checking and the TCP. **(b) the actuation pipeline** (DIO via ICON ADIO, or a gripper service driver).
- **Caveats** (verified against source; the tutorial is partly aspirational):
  - `load("//intrinsic/assets/build_defs:asset.bzl", "intrinsic_asset")`: **no such rule**. Use `intrinsic_scene_object` (geometry only) or `intrinsic_hardware_device` (+ `intrinsic_service`).
  - `manifest.textproto` with `intrinsic_proto.assets.AssetManifest` / `type: HARDWARE_DEVICE`: **no such message**. Use `SceneObjectManifest` or `HardwareDeviceManifest`.
  - The SDF `<frame name="tool_frame">` lacks `intrinsic:create_entity="true"` and the xmlns, so it would be dropped.
  - `intrinsic_asset_instance(config=":wsg32...textproto")` passes an Any config as `config`. Use `service_config`.
  - Asset `ai.intrinsic.wsg32_gripper_strauss` exists nowhere in the repo.
  - Real, working patterns: the Robotiq hardware device (`intrinsic-core/intrinsic/resources/catalog/resourcedata/gripper/`) and the OMTS DIO gripper (`intrinsic-omts/src/hardware/gripper.py`).

## 10. moveit_grasp_planning.md: MoveIt planning scene and grasp planner

- **Steps:**
  1. Build `moveit_planning_service` in a colcon workspace (`intrinsic-ai/intrinsic-moveit`, `lyrical.repos`).
  2. Deploy OMTS (the tutorial pins OMTS commit `48be90d`).
  3. `ros2 launch moveit_planning_service service.launch.py headless:=false start_service_status_monitor:=false` with the Zenoh env.
  4. Jog and run `apply_scene_updates --files configs/omts/raw_stock_in_vise.updates.pbtxt`; the MoveIt scene follows.
  5. `bazel run //third_party/intrinsic_moveit/tools:moveit_plan_grasp_and_move -- --address=localhost:17080 --target_object=raw_stock_2x3x5 [--plan_only] --surfaces=0,1,4,5`
  6. `omts_app ... --config=configs/omts/app_config.yaml --grasp_planner=moveit`
- **Why:** the MoveIt service mirrors the ObjectWorld collision geometry into its planning scene, so scene edits (world updates) immediately affect grasp planning. Surfaces 0, 1, 4 and 5 are the long faces of the 2×3×5 stock.

## 11. Interactive ICON tutorials (`interactive_tutorials/icon/`)

- `robot_bringup.md` (KUKA KR6 / UR in your own Bzlmod workspace, `env.sh` inctl wrapper)
- `icon_introduction/icon_introduction.md` (parts, actions, reactions, safety actions, IconMainConfig, autoGenerate endpoint)
- `hardware_modules/custom_hardware_modules.md` (loopback HWM, RT rules)
- `ros2_bridge_tutorial.md` (`icon-hwm-controller`)
- `client_api/move_to_contact_tutorial.md` (enable the UR FT sensor part, `move_to_contact` skill; OMTS forces 15/8/15/5 N)

All of these are digested in `intrinsic-hardware-assets/references/hardware-devices-and-icon.md`.

⚠️ `robot_bringup.md`, `files/env.sh` and `custom_hardware_modules.md` invoke `@intrinsic-core//intrinsic/tools/inctl:inctl_external` or `//intrinsic/tools/inctl:inctl_external`. Neither exists. The real target is `//intrinsic_sdk/intrinsic/tools/inctl:inctl_external`, at 20261012.0 and at the pin. Alternatively, use the installed `inctl` binary.

⚠️ `robot_bringup.md`, `guides/commission_solution/set_up_robot/kuka_rsi_setup.md` and `universal_robots_setup.md` load `intrinsic_asset_instance` from `@intrinsic-core//intrinsic/assets/build_defs:asset.bzl`. That file is deleted at c40e02a (the OMTS pin), so use `@intrinsic-core//intrinsic_sdk/intrinsic/assets/build_defs:asset.bzl`.

## Platform concepts docs

- `learn/platform_introduction/world_concepts.md`: objects, entities (link, joint, frame, sensor), attachment frames, belief vs simulated world, sensing vs editing.
- `learn/glossary/{intrinsic_terms,general_terms}.md`: terminology.
- `assets/create_new_assets/convert_3d_models.md`: CAD → SDF, see `sdf-authoring.md`. ⚠️ It has the same wrong `intrinsic_scene_object` load path as tutorial 7.
