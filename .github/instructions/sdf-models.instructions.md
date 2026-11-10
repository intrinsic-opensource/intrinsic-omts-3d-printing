---
description: "Use when creating or editing SDF models (*.sdf, *.sdf.xacro) for Intrinsic scene objects or hardware parts: links, joints, frames, collisions, inertia, meshes, intrinsic:create_entity attributes."
applyTo: "**/*.sdf, **/*.sdf.xacro"
---
# SDF rules for Intrinsic scene objects

Full reference: `.agents/skills/intrinsic-hardware-assets/references/sdf-authoring.md`.

## Model structure

- Write one `<model>` per file. Everything is in **meters**, and `<pose>` angles are **radians** (`x y z roll pitch yaw`).
- Give every dynamic link `<inertial>` with mass and inertia. Use `<static>true</static>` for fixtures, enclosures and vises so they don't fall in Gazebo.
- Visuals should be `.glb` (preferred). Collisions should use primitives (`box`, `cylinder`, `sphere`, `capsule`) or a low-poly mesh. Watch polycount: < 25k triangles for grippers, < 200k for enclosures.
- Mesh `<uri>` paths are relative to the SDF, or use `model://<workspace path>`. **Every referenced mesh must be listed in `sdf_assets`** of the `sdf_scene_object` rule.
- Joints are `prismatic`/`revolute` with `<axis><xyz>` and `<limit><lower>/<upper>` (m or rad). Moving links need their own mesh.

## Frames and names

- Frames are **dropped** unless explicitly marked:
  - Declare `xmlns:intrinsic="https://intrinsic.ai/"` on `<sdf>`.
  - Use `intrinsic:create_entity="true"` for a frame entity, e.g. a TCP `tool_frame`.
  - Use `intrinsic:create_attachment_entity="true"` for an attachment frame, e.g. a flange.
- Link, joint and frame names are referenced elsewhere (`entity_names` filters, ICON configs, OMTS `gripper_body`/`tool_frame`). **Renaming them breaks scene updates and configs.** Grep before renaming.
- The world object name is the **asset instance name**, not `<model name>`.

## After editing

- Rebuild with `bazel build //<pkg>:<target>`.
- Inspect `bazel-bin/<pkg>/<sdf_scene_object_name>.pbtxt` to confirm the entities.
- Redeploy or reinstall, then run `inctl world reset --address localhost:17080`.
- If you see `No suitable reader found for ... .glb`, run `git lfs pull`.
