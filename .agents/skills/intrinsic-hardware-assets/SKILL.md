---
name: intrinsic-hardware-assets
description: 'Create or edit hardware parts and physical assets for Intrinsic Core / OMTS. Covers SDF models (links, joints, frames, intrinsic:create_entity, collisions, inertia, static); meshes (GLB/OBJ/STL, CAD to SDF, Blender SDF_Gen); the sdf_scene_object, intrinsic_scene_object, intrinsic_hardware_device, intrinsic_service and intrinsic_asset_instance Bazel rules; SceneObjectManifest and HardwareDeviceManifest; grippers (DIO vs PinchGripperPart driver); cameras; robot hardware modules and ICON config (UR, KUKA); mounting tools on the flange; swapping robots; inctl asset install and service add; runtime SceneObject import. Use when adding or modifying a workpiece, fixture, enclosure, vise, gripper, camera, robot, or its geometry, collision, mass, joints, or TCP.'
---

# Creating and editing hardware parts (Intrinsic Core / OMTS)

Paths are relative to `/home/berti/gits/`. **Simulation first** (`--operation_mode=sim`). Ask before any real-hardware action.

## Pick the asset kind

| You need… | Build this | Example to copy |
|---|---|---|
| Passive geometry: workpiece, fixture, enclosure, mount plate | **Scene object**: `sdf_scene_object` + `intrinsic_scene_object` | `intrinsic-omts/models/raw_stock_2x3x5/`, `models/camera_mount/`, `models/omts_enclosure/` |
| Geometry with joints but no driver (vise jaws, CNC door) | Scene object with SDF joints; drive the joints via `update_object_joints` and the `update_world` skill | `intrinsic-omts/models/schunk_egp_64nnb/` + `src/hardware/machine.py` |
| Reuse a core model under your own ID | `intrinsic_scene_object(scene_object="@intrinsic-core//...")` | `intrinsic-omts/models/cnc_enclosure/BUILD` |
| End-effector actuated by robot digital I/O | Scene object + mounting updates + `dio_set_output` skills | OMTS `DioGripper` |
| Device with its own driver (gripper, camera, sensor) | **Hardware device**: scene object + `intrinsic_service` (+ `intrinsic_data`) + `intrinsic_hardware_device` | `intrinsic-core/intrinsic/resources/catalog/resourcedata/gripper/BUILD` |
| A robot arm | Existing HWM hardware device (UR/KUKA/ABB) + ICON config; or a custom C++ HWM or the `ros2_control` bridge | `intrinsic-omts/BUILD` (`ur_module`, `icon`) |
| Quick import of a mesh or STEP file without Bazel | gRPC `SceneObjectImport` + `InstalledAssets` | [runtime-scene-object-import.md](./references/runtime-scene-object-import.md) |

## Workflow 1: new part (scene object), end to end

Run all of this from the intrinsic-omts repo root (or your solution repo).

1. **Files** go in `models/<part>/`:
   - `<part>.sdf` (see the templates in [sdf-authoring.md](./references/sdf-authoring.md))
   - meshes (`*.glb`)
   - `<part>_manifest.textproto` (must end in `.textproto`)
   - `BUILD`
2. **BUILD**, using load paths valid at the OMTS core pin (they match `models/*/BUILD`):
   ```python
   load("@intrinsic-core//intrinsic/scene/build_defs:sdf_scene_object.bzl", "sdf_scene_object")
   load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl", "intrinsic_scene_object")

   package(default_visibility = ["//visibility:public"])

   sdf_scene_object(
       name = "my_part_scene_object",
       src = "my_part.sdf",
       sdf_assets = ["visual.glb"],          # every mesh the SDF references
   )

   intrinsic_scene_object(
       name = "my_part",
       manifest = "my_part_manifest.textproto",   # metadata.id {package:"ai.intrinsic" name:"my_part"}
       scene_object = ":my_part_scene_object",
   )
   ```
3. **Build** with `bazel build //models/my_part:my_part`. Inspect `bazel-bin/models/my_part/my_part_scene_object.pbtxt` to confirm the links, joints and frames.
4. **Try it live** (lost on redeploy):
   ```bash
   inctl asset install bazel-bin/models/my_part/my_part.bundle.tar --address localhost:17080
   inctl service add ai.intrinsic.my_part --name my_part --address localhost:17080
   inctl world reset --address localhost:17080         # the new object appears at root origin
   ```
5. **Place it** with an `update_transform` in a cell updates file (see the `intrinsic-scene-editing` skill).
6. **Make it permanent** in `intrinsic-omts/BUILD`:
   - Add `"//models/my_part"` to `omts_solution.assets` (in the right `select` branch).
   - Add `intrinsic_asset_instance(name = "my_part", asset = "ai.intrinsic.my_part")` and list `":my_part"` in `instances`. `BUILD` already loads `intrinsic_asset_instance` from `@intrinsic-core//intrinsic_sdk/intrinsic/assets/build_defs:asset.bzl`.
   - Add the placement `.updates.pbtxt` to `object_world_updates`.
7. Redeploy, reset, and verify:
   ```bash
   bazel run //:omts_solution -c opt [--config=lab_bb_01] -- --address localhost:17080 --operation_mode=sim
   inctl world reset --address localhost:17080
   ```
   Then run `bazel --quiet run //tools/world:inspect_world -- --address localhost:17080` and check RViz and Gazebo. A part that should not fall must be `<static>true</static>`.

## Workflow 2: articulated part (vise, door, slide)

1. Model the joints in the SDF (`prismatic`/`revolute`, axis, limits in m/rad). Give each moving link its own mesh.
2. Set the initial joint values in a cell updates file with `update_object_joints { object {...} joint_positions: ... }`, in joint declaration order.
3. To change them at runtime, inside a behavior tree use `update_world` with `ObjectWorldUpdate(update_object_joints=...)`. Pattern: `intrinsic-omts/src/hardware/machine.py` `_build_world_joint_update_task`. Keep the open and closed values in `app_config.yaml` (`machine.door_open_joints`, etc.).

## Workflow 3: tool on the robot (gripper, camera, bracket)

1. In the SDF, the base link is the mounting face. Declare the TCP: `<frame name="tool_frame" attached_to="<body_link>" intrinsic:create_entity="true">`. The frame is dropped if the attribute is missing.
2. Add a cell `*.updates.pbtxt` that:
   - sets flange → tool with `update_transform`
   - optionally sets the tool → `tool_frame` offset
   - runs `reparent_object` to the robot with `include_final_entity`
   - runs `update_kinematic_object_properties` on the robot

   Copy `intrinsic-omts/configs/omts/ur_module.attachments.updates.pbtxt`.
3. Name the instance `gripper`. OMTS tools and `app_config.yaml` default to `gripper`/`tool_frame`; otherwise pass `--tool_object` and edit `robot.tool_object_name`.
4. Verify with `inspect_world`. The `Tool Frame in root` pose must sit at the expected offset from `Flange in root`.

## Workflow 4: actuated device (hardware device)

1. Choose the actuation (details in [hardware-devices-and-icon.md](./references/hardware-devices-and-icon.md)):
   - **DIO**: no new service. Use `dio_set_output` / `dio_wait_for_input` on ICON `adio` exports such as `standard_out`.
   - **Pinch-gripper driver**: an `intrinsic_service` running `resource-pinch-gripper-server-image.tar` with a `PinchGripperPart` Any `default_config` (`pinch_gripper_driver_name`). Control it with the `control_pinch_gripper` skill.
2. Create three manifests:
   - a scene object manifest (id `<x>_scene_object`)
   - a service manifest (id `<x>_service`, `service_def` with `real_spec`/`sim_spec` images)
   - a `HardwareDeviceManifest` whose `graph.nodes` are `"scene_object"` and `"service"`, referencing those IDs
3. Wire it in BUILD:
   - `intrinsic_hardware_device(name="<x>", manifest=..., assets=[":<x>_scene_object_node", ":<x>_service_node"])`
   - `intrinsic_asset_instance(asset="ai.intrinsic.<x>", instance_name="gripper", service_config=...)` to override the driver config per cell
4. Add the device to the solution `assets` + `instances`, and add the mount updates (Workflow 3). Redeploy. Check `inctl asset instance list` and `inctl service state list`.

## Workflow 5: swap or reconfigure the robot

Keep **one name** consistent across BUILD `instance_name`, every `*.updates.pbtxt`, the ICON `module_name`/`hardware_resource_name`, and `app_config.yaml`. Match `control_frequency_hz` between ICON and the HWM, and only reference interfaces the HWM exports. The full UR→KUKA recipe and error table are in [hardware-devices-and-icon.md](./references/hardware-devices-and-icon.md).

## Workflow 6: change a part that ships with intrinsic-core (from OMTS)

OMTS builds core from a pinned commit (`MODULE.bazel`: `INTRINSIC_CORE_COMMIT` = c40e02a, `git_override`), so editing `../intrinsic-core` has no effect.

1. Write the patch against the pinned commit: `git -C ../intrinsic-core show c40e02a:<path>` gives the base file. Create it as a `-p1` patch in `intrinsic-omts/bazel/patches/`.
2. Export it in `bazel/patches/BUILD`.
3. Add it to `git_override(module_name="intrinsic-core", patches=[...])` in `MODULE.bazel`.

Example: `robotiq_hande_finger_offset.patch` shifts the Hand-E finger links ±5 mm. Alternatively, wrap the core scene object in your own `intrinsic_scene_object`, or override per instance with SceneObjectUpdates (`sdf_scene_object(updates_pbtxts=[...])`).

## Verification and troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No suitable reader found for the file format of file "...glb"` | The mesh is a git-lfs pointer. Run `git lfs install && git lfs pull`. |
| `no such package '@intrinsic-core//intrinsic/assets/scene_objects/build_defs'` | Tutorial path bug. Use `@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl`. |
| `intrinsic_asset` not found | That rule doesn't exist. Use `intrinsic_scene_object` or `intrinsic_hardware_device`. |
| `no such file 'intrinsic/assets/build_defs/asset.bzl'` or `'intrinsic/scene/build_defs/scene_object.bzl'` | These legacy forwarders are deleted at the OMTS core pin. Load from `@intrinsic-core//intrinsic_sdk/intrinsic/assets/build_defs:asset.bzl` or `//intrinsic_sdk/intrinsic/scene/build_defs:scene_object.bzl`. |
| A frame from the SDF is missing in the world | The `intrinsic:create_entity="true"` attribute or the `xmlns:intrinsic` declaration is missing. |
| The part falls through or away in Gazebo | It is not static or has no collision. Add `<static>true</static>` or `simulation_component { is_static: true }`. |
| `failed to process Asset ...: could not upload ... to CAS ... Unimplemented` | Runtime services are not healthy. Check `k9s -n app-intrinsic-base -c pods`, then redeploy intrinsic-base. |
| `dial unix /run/containerd/containerd.sock: connect: connection refused` | Delete the `artifacts-deployment-*` pod in k9s (`app-intrinsic-base`), then retry. |
| `disk quota exceeded` / `no space left` during deploy | Use `TMPDIR=~/tmp bazel run //:omts_solution -- ...` |
| `"gripper" has multiple final entities` | ObjectWorldUpdates: use `entity_names` filters. `attach_object_to_robot`: works with the gripper at the core pin c40e02a; at 20261012.0, pass the arm (`ur_module`). |
| `test_world_configs` fails after editing `configs/` | A pbtxt doesn't parse, the scene frame set changed (update `_EXPECTED_SCENE_FRAMES`), or a file other than `align_robot` moves `ur_module`. |
| `operation mode unspecified` on `inctl service add` | No running solution. Deploy first. |

## References

- [sdf-authoring.md](./references/sdf-authoring.md): SDF rules, custom `intrinsic:` tags, templates (static, dynamic, articulated, end-effector), CAD and Blender paths.
- [bazel-asset-rules.md](./references/bazel-asset-rules.md): verified load labels, rule attributes, manifests, and install commands.
- [hardware-devices-and-icon.md](./references/hardware-devices-and-icon.md): grippers, ICON parts and configs, HWM configs, robot swap, real bring-up, custom HWM, faults.
- [runtime-scene-object-import.md](./references/runtime-scene-object-import.md): gRPC import of OBJ/STEP with unit scale, material and collision options.
- Scene placement and mounting syntax: `.agents/skills/intrinsic-scene-editing/`.
