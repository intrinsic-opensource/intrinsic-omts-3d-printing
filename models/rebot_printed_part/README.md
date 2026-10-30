# reBot Printed-Part Simulation Model

`rebot_printed_part` is a 40 × 40 × 30 mm, 20 g box used as a lightweight
workpiece for the reBot's pick-and-place demo in simulation. Its collision
is an SDF `<box>`; its visual is `printed_part_visual.glb`, because
`flowstate_ros_bridge` (RViz) only draws mesh visuals and skips primitives.

The part starts in the middle of the printer's bed
([`configs/rebot/printed_part.updates.pbtxt`](../../configs/rebot/printed_part.updates.pbtxt)),
where `omts_app` finds it with the wrist camera and picks it
([`configs/rebot/app_config.yaml`](../../configs/rebot/app_config.yaml)). The
reBot gripper closes on the part, and Gazebo holds it while the gripper is
closed; the app also attaches it to the robot in the belief world for motion
planning.

The GLB is a plain box written with `write_glb` from
[`tools/models/urdf_to_sdf.py`](../../tools/models/urdf_to_sdf.py).
