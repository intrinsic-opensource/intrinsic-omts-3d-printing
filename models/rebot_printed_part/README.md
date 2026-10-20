# reBot Printed-Part Simulation Model

`rebot_printed_part` is a 40 × 40 × 30 mm, 20 g box used as a lightweight
workpiece for the reBot's simulation-only pick-and-place demo. Its collision
is an SDF `<box>`; its visual is `printed_part_visual.glb`, because
`flowstate_ros_bridge` (RViz) only draws mesh visuals and skips primitives.

The reBot demo places the part at source A and defines fixed, top-down grasp
frames at A and B in [`configs/rebot/rebot_pick_place.updates.pbtxt`](../../configs/rebot/rebot_pick_place.updates.pbtxt).
The app uses `GridInfeedStrategy` for the fixed workpiece identity and attaches
or detaches the part in the Object World to stand in for gripping. This moves
the part in the belief world (RViz) only; Gazebo's copy stays where it is.
Finger actuation is intentionally not included.

The GLB is a plain box written with `write_glb` from
[`tools/models/urdf_to_sdf.py`](../../tools/models/urdf_to_sdf.py).
