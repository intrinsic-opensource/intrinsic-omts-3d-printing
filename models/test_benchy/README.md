# Test 3DBenchy (low poly)

A low-poly [3DBenchy](https://3dbenchy.com), the 3D-printing benchmark boat,
as a real print for the reBot graspability trials
(`research/tools/README.md`). Deployed with `//:rebot_solution` only under
`--//:test_parts`.

`obj_1_3DBenchy.stl` is the low-poly model as received: 900 triangles, in
millimetres, 59.5 × 31.0 × 48.0 mm, with x along the hull and z up, centred
at (90, 90) mm on a build plate. `test_benchy.stl`, the mesh the part uses,
is the same model shifted by (−90, −90, −24) mm so that its origin is the
centre of its bounding box; `test_benchy.sdf` scales it to metres. The
origin has to be in the mesh itself: the pose estimator's registration
exports the mesh without the SDF visual's pose (`research/HANDOFF.md`,
step 4c).

Why a low-poly model: the official single-part STL (225,706 triangles,
[CreativeTools/3DBenchy](https://github.com/CreativeTools/3DBenchy)) made the
NVIDIA pose estimator's FoundationPose run out of GPU memory on a 16 GB GPU.
Only the shape matters here. 3DBenchy is public domain (CC0) since 2025, so
modified versions may be redistributed
([license](https://www.3dbenchy.com/license/)).

Source of this low-poly model: TODO.
