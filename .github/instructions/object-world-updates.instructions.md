---
description: "Use when creating or editing Intrinsic ObjectWorldUpdates files (*.updates.pbtxt): scene frames, transforms, robot base pose, tool/gripper/camera mounting, joint positions or limits, collisions. Rules for intrinsic_proto.world.ObjectWorldUpdates textprotos."
applyTo: "**/*.updates.pbtxt"
---
# ObjectWorldUpdates file rules

Full reference: `.agents/skills/intrinsic-scene-editing/references/object-world-updates.md`. Workflows: `.agents/skills/intrinsic-scene-editing/SKILL.md`.

## Writing the file

- Start with the header:
  ```
  # proto-file: intrinsic/world/public/proto/object_world_updates.proto
  # proto-message: intrinsic_proto.world.ObjectWorldUpdates
  ```
  Then add one `updates { <one_variant> { ... } }` block per change.
- Every `object_name` must equal an **instance name** that exists in the deployed solution (`inspect_world` lists them). `root` is the world origin.
- Units are meters and **radians**. Ignore the "degrees" comment in `UpdateObjectJointsRequest`.
- Quaternions are `x y z w`. **Always write `w`**: omitted fields are 0, so a missing `w` is not identity.
- In `update_transform`, set `node_to_update` whenever `node_a` and `node_b` are not direct parent and child. It moves only the local pose and never reparents.
- To mount a tool, keep this order:
  1. `update_transform` flange → tool
  2. optional tool → `tool_frame` (with `node_a_filter.entity_names`)
  3. `reparent_object` with `entity_filter { include_final_entity: true }`
  4. `update_kinematic_object_properties` on the robot
- Prefer `reparent_object.parent_object` over the deprecated `new_parent`.
- `include_final_entity` fails on multi-leaf objects such as gripper fingers. Use `entity_names: "<link>"` instead.
- `create_frame` fails if the frame already exists. Use `update_transform` with `node_b`/`node_to_update` set to that frame.
- To persist a named joint configuration in source, use `update_kinematic_object_properties.named_joint_configurations_to_set`.

## Wiring and verifying

- Files apply in list order, and later files override earlier ones. To make a file permanent, add its label to `intrinsic_solution(object_world_updates=...)` in the **`select()` branch matching the deploy cell** (`--config=lab_bb_01` / `--//:setup=lab_bb_01`), then redeploy and run `inctl world reset`.
- Test live first. **Always pass `--files`.** Without it, the tool applies every file in `configs/<--setup>/`.
  ```bash
  bazel --quiet run //tools/world:apply_scene_updates -- --address localhost:17080 --files <file>
  ```
  Verify with `bazel --quiet run //tools/world:inspect_world -- --address localhost:17080`.
- The test `bazel test //tests/unit:test_world_configs` must pass for files under `configs/`:
  - every file parses and is non-empty
  - the `create_frame` set in `scene.updates.pbtxt` must equal `_EXPECTED_SCENE_FRAMES` in `tests/unit/test_world_configs.py` (update it together with the frames)
  - only `align_robot.updates.pbtxt` may move `ur_module`
- If you add or rename frames used by the OMTS app, update `configs/<cell>/app_config.yaml` (`frames:`).
