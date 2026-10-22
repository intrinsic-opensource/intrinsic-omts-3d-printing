# reBot Printed-Part Simulation Model

`rebot_printed_part` is a 40 × 40 × 30 mm, 20 g box used as a lightweight
workpiece for the reBot's pick-and-place demo in simulation. Its collision
is an SDF `<box>`; its visual is `printed_part_visual.glb`, because
`flowstate_ros_bridge` (RViz) only draws mesh visuals and skips primitives.

The reBot demo places the part at source A and defines fixed, top-down grasp
and rest frames at A and B in [`configs/rebot/rebot_pick_place.updates.pbtxt`](../../configs/rebot/rebot_pick_place.updates.pbtxt).
The app uses `GridInfeedStrategy` for the fixed workpiece identity. The reBot
gripper closes on the part, and Gazebo holds it while the gripper is closed.
The app also attaches the part to the robot in the belief world for motion
planning, and snaps it onto the destination's rest frame after each place.

The GLB is a plain box written with `write_glb` from
[`tools/models/urdf_to_sdf.py`](../../tools/models/urdf_to_sdf.py).
