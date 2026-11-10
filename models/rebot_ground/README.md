# reBot Simulation Ground

`rebot_ground` is a static 2 × 2 m solid slab with a 5 cm thickness. It is
placed by [`configs/rebot/rebot_ground.updates.pbtxt`](../../configs/rebot/rebot_ground.updates.pbtxt)
with its top surface at `z=0`, supporting the printed part initially placed at
`z=0.015`. The collision is an SDF `<box>`; the visual is `ground_visual.glb`
(a plain box written with `write_glb` from `tools/models/urdf_to_sdf.py`)
because RViz only draws mesh visuals.
