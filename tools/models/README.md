# Scene Model Tools (`tools/models/`)

Utilities for producing scene models under [`models/`](../../models/).

## CLI Targets

| Target | Source File | Description |
| :--- | :--- | :--- |
| `//tools/models:urdf_to_sdf` | [`urdf_to_sdf.py`](urdf_to_sdf.py) | Converts a URDF with STL meshes into an SDF model plus one visual and one collision GLB per link. Meshes are simplified by vertex clustering, written Z-up, and colored by optional file-name rules. Joints keep their URDF origins, axes and limits. |

## Usage Example

```bash
# Regenerate the reBot model (paths may be relative to where bazel is run):
bazel run //tools/models:urdf_to_sdf -- \
  --urdf=/path/to/robot.urdf --mesh_dir=/path/to/meshes \
  --out_dir=models/rebot_b601_rs --model_name=rebot_b601_rs \
  --colors=models/rebot_b601_rs/mesh_colors.json --static
```

`--visual_cell_size` and `--collision_cell_size` (meters, defaults 0.5 mm and
5 mm) trade mesh detail for file size. Color rules are a JSON list of
`{"pattern", "rgba", "metallic", "roughness"}`, matched in order against each
visual mesh's file name (`fnmatch`, case-insensitive).
