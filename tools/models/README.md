# Scene Model Tools (`tools/models/`)

Utilities for producing scene models under [`models/`](../../models/).

## CLI Targets

| Target | Source File | Description |
| :--- | :--- | :--- |
| `//tools/models:urdf_to_sdf` | [`urdf_to_sdf.py`](urdf_to_sdf.py) | Converts a URDF with STL meshes into an SDF model plus one visual and one collision GLB per link. Meshes are simplified by vertex clustering, written Z-up, and colored by optional file-name rules. Joints keep their URDF origins, axes and limits. |

## Usage Example

```bash
# Convert a URDF into a static scene model (paths may be relative to where
# bazel is run):
bazel run //tools/models:urdf_to_sdf -- \
  --urdf=/path/to/robot.urdf --mesh_dir=/path/to/meshes \
  --out_dir=models/my_model --model_name=my_model --static
```

The reBot arm and gripper commands are in
[`models/rebot_b601_rs/README.md`](../../models/rebot_b601_rs/README.md).

To split one URDF into several models, such as an arm and its gripper, use
`--root_link` (start from this link) and `--exclude_links` (leave these
subtrees out). For a robot arm that ICON controls, `--ik_solver` adds
`intrinsic:ik_solver` and Cartesian limits, and `--flange_link` adds the
`flange` attachment frame where tools mount.

`--collision_boxes` takes a JSON file of box collisions by link,
`{"link": [{"pose": [x, y, z, roll, pitch, yaw], "size": [sx, sy, sz]}]}`
in the link frame, which replace that link's collision meshes. Use it where a
mesh collides badly: Gazebo approximates mesh collisions with a convex
decomposition, which fills concave parts such as a gripper finger.

`--visual_cell_size` and `--collision_cell_size` (meters, defaults 0.5 mm and
5 mm) trade mesh detail for file size. Color rules are a JSON list of
`{"pattern", "rgba", "metallic", "roughness"}`, matched in order against each
visual mesh's file name (`fnmatch`, case-insensitive).
