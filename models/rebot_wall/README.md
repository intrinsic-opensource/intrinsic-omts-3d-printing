# reBot Simulation Wall

`rebot_wall` is a static wall obstacle for the reBot cell, placed by
[`configs/rebot/rebot_wall.updates.pbtxt`](../../configs/rebot/rebot_wall.updates.pbtxt).

The wall's size is set twice, and both must match:

* the collision `<box>` in `rebot_wall.sdf`, used by the planner and physics;
* the visual `wall_visual.glb`, drawn by Gazebo and RViz (RViz skips SDF
  primitives, so the visual must be a mesh).

After changing the box, regenerate the GLB with the same full sizes in meters
(`X Y Z` below), from the repository root:

```bash
X=0.22 Y=0.01 Z=0.18 python3 - <<'PY'
import os, sys
import numpy as np
sys.path.insert(0, "tools/models")
from urdf_to_sdf import MeshPart, write_glb
hx, hy, hz = (float(os.environ[k]) / 2 for k in ("X", "Y", "Z"))
v = np.array([[x, y, z] for x in (-hx, hx) for y in (-hy, hy) for z in (-hz, hz)])
f = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
              [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
write_glb("models/rebot_wall/wall_visual.glb",
          [MeshPart(name="wall", vertices=v, faces=f, rgba=(0.85, 0.45, 0.15, 1.0))])
PY
```

Keep the placement's `z` at half the height so the wall stands on the ground.
Then redeploy, and restart the ROS bridge pod so RViz fetches the new mesh.
