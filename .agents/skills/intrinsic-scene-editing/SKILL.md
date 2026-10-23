---
name: intrinsic-scene-editing
description: 'Modify Intrinsic Core / OMTS scenes (the workcell world). Covers adding, moving or deleting frames; relocating the robot base; mounting grippers, cameras or tools on the flange (reparent); setting joint positions, limits and named joint configurations; enabling or disabling collisions; making objects static in Gazebo; ObjectWorldUpdates *.updates.pbtxt files, intrinsic_solution object_world_updates, apply_scene_updates, inspect_world, edit_frames_rviz, store_frame, inctl world reset, init_world vs belief world vs sim_world, and the solution.world Python API. Use when editing scene.updates.pbtxt, cell layout, frames, transforms, TCP, or attachments.'
---

# Editing scenes (ObjectWorld) in Intrinsic Core / OMTS

Paths are relative to `/home/berti/gits/`. The cluster gateway is `localhost:17080`. **Default to simulation.** Never move real hardware without explicit user confirmation.

## Mental model (read once)

- **World** = a tree. `root` → objects → entities (links, joints, frames, sensors). Every entity is posed relative to its parent. An object's pose is the pose of its *base entity*. Units: meters, radians, quaternion `x y z w`.
- **Object** = an instance of a scene-object or hardware-device asset. Its name is the `instance_name` of the `intrinsic_asset_instance` (e.g. `ur_module`, `gripper`, `enclosure`). A **kinematic object** has joints (robots, grippers, doors, vises).
- **Frame** = a named pose on an object, entity, or frame (e.g. `ur_module/flange`, `gripper/tool_frame`, global `root/view`). An **attachment frame** defines where a child object attaches.
- **Three worlds:**
  - `init_world` is built at deploy from `object_world_updates`.
  - `world` (belief) is a copy of init after deploy or reset, and is live-updated by ICON and skills.
  - `sim_world` (Gazebo) is cloned from belief on simulator reset.
- `inctl world reset` = `init_world` → `world`, then the simulator restarts from the new belief world. RViz shows belief (via the ROS bridge `/workcell_markers` and `/tf`). Gazebo shows `sim_world`.
- `update_transform(node_a, node_b, a_t_b, node_to_update)` rewrites **only `node_to_update`'s local pose** so that `a_t_b` holds. It never reparents. `reparent_object` changes attachment.

## Decision: where should the change live?

| Goal | Mechanism | Persistence |
|---|---|---|
| Try a pose quickly | `bazel run //tools/world:apply_scene_updates -- --files /tmp/x.updates.pbtxt` (OMTS) or `world.batch_update(...)` | Lost on `inctl world reset` |
| Keep it across resets but not deploys | `--update_init_world`, or Python on `init_world` | Lost on redeploy |
| **Permanent cell layout** | Edit/add `configs/<cell>/*.updates.pbtxt`, list it in `intrinsic_solution(object_world_updates=select({...}))`, redeploy, `inctl world reset` | Permanent (source) |
| True for every instance of a part | `SceneObjectUpdates` in `sdf_scene_object(updates_pbtxts=[...])`, or edit the SDF | Permanent (asset) |
| Change during process execution | `update_world` skill (`UpdateWorldParams{update \| updates}`), `attach_object_to_robot`, `detach_object`, `create_object` skill, `bt.PythonScript` | Runtime only |
| Teach a frame with the robot | Jog or `move_to_frame`, then `bazel run //tools/jogging:store_frame -- <name>` | Written to the pbtxt file + live world |
| Drag frames visually | `bazel run //tools/world:edit_frames_rviz` | Auto-saved to pbtxt on mouse release |

## Workflow A: live edit (no rebuild)

1. Check the current state from the repo root:
   ```bash
   bazel --quiet run //tools/world:inspect_world -- --address localhost:17080
   ```
2. Write an updates file such as `/tmp/x.updates.pbtxt`, starting from the templates in [object-world-updates.md](./references/object-world-updates.md). Object and frame names must match `inspect_world` output exactly.
3. Apply it:
   ```bash
   bazel --quiet run //tools/world:apply_scene_updates -- --address localhost:17080 --files /tmp/x.updates.pbtxt
   ```
   This applies the file to the belief world and, because `--reset_sim` defaults to true, also resets Gazebo. **Always pass `--files` for a targeted edit.** Without it, the tool applies *every* `configs/<--setup>/*.updates.pbtxt` (default `omts`) in alphabetical order, including `raw_stock_in_vise.updates.pbtxt`. On real hardware it skips joint updates.
4. Verify with `inspect_world` again. In RViz, set Fixed Frame `root`, add a TF display, and add a MarkerArray on `/workcell_markers` with Durability Transient Local.
5. Undo with `inctl world reset --address localhost:17080`.

## Workflow B: make it permanent

1. Put the file in the cell directory, e.g. `intrinsic-omts/configs/omts/my_cell.updates.pbtxt`. `configs/BUILD` exports `*/*.pbtxt` automatically. Alternatively, put it in the repo root and reference it as `":file.updates.pbtxt"`, which is what the tutorial does.
2. In `intrinsic-omts/BUILD` → `omts_solution` → `object_world_updates = select({...})`, append the label to **the branch you deploy**:
   - `"//conditions:default"` for the omts cell
   - `":is_lab_bb_01"` for `--config=lab_bb_01` / `--//:setup=lab_bb_01`

   Order matters: later files override earlier ones, and anything that references an object must come after that object exists (all instances exist before the updates run). The robot base pose belongs **only** in `align_robot.updates.pbtxt`; the test enforces this.
3. Check the tests:
   ```bash
   bazel test //tests/unit:test_world_configs
   ```
   If you added or removed `create_frame`s in a `scene.updates.pbtxt`, update `_EXPECTED_SCENE_FRAMES` in `tests/unit/test_world_configs.py`.
4. Redeploy, then reset:
   ```bash
   bazel run //:omts_solution -c opt [--config=lab_bb_01] -- --address localhost:17080 --operation_mode=sim
   inctl world reset --address localhost:17080
   ```
5. Verify with `inspect_world`, RViz, and Gazebo.
6. If you renamed or added frames the app uses, update `configs/<cell>/app_config.yaml` (`frames:` and `robot:`).

## Workflow C: teach frames and joint configs with the robot

```bash
bazel run //tools/jogging:jog_interactive -- --host=localhost --port=17080 --instance=icon   # or move_to_frame / move_to_joint
bazel run //tools/jogging:store_frame -- view --address=localhost:17080 \
    [--scene_updates_file configs/lab_bb_01/scene.updates.pbtxt]   # default file is configs/omts/scene.updates.pbtxt
bazel run //tools/jogging:store_joint_config -- home --address=localhost:17080   # world+init_world only, NOT a file
```

`store_frame` stores `root_t_(gripper/tool_frame)` as a `create_frame` entry on `root`. A **new** frame name must also be added to `_EXPECTED_SCENE_FRAMES` in `tests/unit/test_world_configs.py`. To persist a joint configuration in source, add an `update_kinematic_object_properties.named_joint_configurations_to_set` block (see the reference).

## Workflow D: drag frames in RViz (OMTS)

1. Source ROS 2 (needs `rclpy`, `interactive_markers`, `rmw_zenoh_cpp`). Then run:
   ```bash
   bazel run //tools/world:edit_frames_rviz -- --address=localhost:17080 --zenoh_endpoint=tcp/127.0.0.1:7447 \
       [--setup=lab_bb_01] [--frame view place_vise] [--apply_on_start]
   ```
   `--apply_on_start` is off by default since OMTS #165, which preserves the real robot state. Use `--frame` to limit the markers. If the router listens on 17447 (newer runtime), change the port everywhere.
   If RViz shows no `root` frame, the ROS bridge may be stuck `unconfigured`: `kubectl -n app-resources delete pod rs-flowstate-ros-bridge-0` (see the command reference > RViz troubleshooting).
2. Start RViz with `RMW_IMPLEMENTATION=rmw_zenoh_cpp` and `ZENOH_CONFIG_OVERRIDE='mode="client";connect/endpoints=["tcp/127.0.0.1:7447"]'`.
3. Add an InteractiveMarkers display on `/omts_frame_editor/update` and select the **Interact** tool.

On mouse release the pose is saved into the source `.pbtxt`. The right-click menu offers save, snap to `tool_frame`, revert, and reset Gazebo.

## Workflow E: Python / SBL

`solution.world` (belief) exposes `update_transform`, `create_frame`, `reparent_object_to_final_entity`, `update_joint_positions`, `batch_update`, `reset`, and more. `worlds.ObjectWorld.connect(worlds.EditWorldId.INITIAL, solution.grpc_channel)` gives `init_world`. Full signatures are in [python-world-api.md](./references/python-world-api.md).

## Verification checklist (before you say "done")

- [ ] `inspect_world` lists the object or frame with the expected pose. Flange and tool_frame poses changed only if intended.
- [ ] Names cross-check: `grep -rn '<name>' intrinsic-omts/BUILD intrinsic-omts/configs/` shows `instance_name`, updates, ICON `module_name` and `app_config.yaml` all agree.
- [ ] `bazel test //tests/unit:test_world_configs` passes whenever a `configs/*/*.updates.pbtxt` changed.
- [ ] For permanent edits: redeployed **with the same cell**, then ran `inctl world reset`. Gazebo matches RViz; close and reopen the Gazebo GUI if links look disconnected.
- [ ] Moved static geometry (enclosure, fixtures) is static in sim (`<static>true</static>` in SDF, or `update_object_properties.simulation_component.is_static`). Otherwise it falls under gravity.
- [ ] The motion planner still finds paths: robot base pose vs enclosure (collisions like `Left entity: gripper.gripper_finger2 Right entities: enclosure.base_link`).

## Gotchas (verified)

- `create_frame` on an existing name fails. `apply_scene_updates` auto-converts it to `update_transform`; `batch_update` does not.
- `include_final_entity` fails on objects with multiple leaf links (the gripper fingers). Use `entity_names: "gripper_body"`, or attach to/reference the arm (`ur_module`). The `attach_object_to_robot` skill accepts a gripper at the core pin c40e02a, but not at 20261012.0.
- `apply_scene_updates` without `--files` applies the whole cell directory alphabetically. Only `align_robot.updates.pbtxt` may set the robot base pose.
- Omitting `w` in an orientation means `w = 0`, not identity.
- The `UpdateObjectJointsRequest` proto comment says "degrees", but radians are correct.
- `reparent_object.new_parent` is deprecated; use `parent_object` or `parent_frame`.
- Swapping or renaming a robot instance requires updating every `*.updates.pbtxt` of that cell. Otherwise deploy fails with `No object with name "ur_module" exists`.
- OMTS deploy cell, `omts_app --config=configs/<cell>/app_config.yaml`, and the world tools' `--setup` must match, or you get `Frame with name "pre_place_vise" does not exist`.
- `inctl world reset` while on real hardware can desync belief from reality. Warn the user.
- Joint updates to `world` can be overwritten within ~20 ms by the sensed joint stream from ICON/Gazebo.

## References

- [object-world-updates.md](./references/object-world-updates.md): every update type, field names, templates, and SceneObjectUpdates.
- [python-world-api.md](./references/python-world-api.md): `ObjectWorldClient` signatures, recipes, and the persistence matrix.
- [omts-cell-scene.md](./references/omts-cell-scene.md): OMTS objects, files, frame names, tools and flags, and patching core assets.
- Tutorial source: `intrinsic-core/developer_resources/learn/tutorials/cell_customization.md` and `intrinsic-core/developer_resources/learn/platform_introduction/world_concepts.md`.
- Deep API (gRPC, CloneWorld, SyncObject): `.agents/skills/intrinsic-core-api-overview/references/world-and-kinematics.md` (the tracked upstream copy in this repo).
