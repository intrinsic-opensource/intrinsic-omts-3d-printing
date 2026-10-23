# SDF authoring for Intrinsic scene objects

Sources:

- `intrinsic-core/developer_resources/assets/create_new_assets/convert_3d_models.md`
- Converter tags: `intrinsic-core/intrinsic_sdk/intrinsic/scene/sdf/custom_tags.h`
- Converter code: `intrinsic-core/intrinsic_sdk/intrinsic/scene/sdf/entity_from_sdf.cc`

Working models:

- `intrinsic-omts/models/*/*.sdf`
- `intrinsic-core/intrinsic_control/intrinsic/models/assets/standard_tooling/robotiq_hande/robotiq_hande/robotiq_hande.sdf`
- `intrinsic-core/intrinsic_perception/intrinsic/perception/cameras/hardware_devices/orbbec_gemini_335le.sdf` (sensors)

## Rules

1. **Meters everywhere.** Export CAD in meters or scale in the SDF. The converter rejects meshes whose bounding-box diagonal exceeds `large_mesh_checks_max_mesh_diagonal` if you set it.
2. **One `<model>` per file.** Each `<link>` is a rigid body, and each `<joint>` connects a parent link to a child link.
   - Joint types seen: `prismatic` and `revolute`. Joint `<limit><lower/><upper/>` values are in m or rad.
   - A joint cannot be the base entity, and dependent (multi-parent) joints are unsupported.
3. **Mass and inertia on every dynamic link.** Defaults make simulation and planning implausible. Use `<static>true</static>` for fixtures, enclosures and vises that must not fall in Gazebo.
4. **Visual vs collision:**
   - Visual: high detail, prefer `.glb`.
   - Collision: **primitives** (`box`, `cylinder`, `sphere`, `capsule`, `ellipsoid`, `plane`) or a low-poly mesh. Primitive colliders make simulation and planning much faster.
   - Many small primitive colliders per link is fine. The Schunk vise uses about 10.
5. **Mesh URIs** are relative to the `.sdf` file (e.g. `<uri>visual.glb</uri>` or `meshes/x.glb`) **and must be listed in `sdf_assets`** of the `sdf_scene_object` rule. Core models use `model://<workspace-relative path>` URIs, e.g. `model://intrinsic_control/intrinsic/models/assets/standard_tooling/robotiq_hande/base_visual.glb`, with a `model.config` next to the SDF.
6. **Mesh formats:** GLB is preferred (mesh, materials and textures in one file), then FBX, then OBJ. STL has no materials, so use it only as a last resort or for collision. `.dae` also appears in tutorials. If a build fails with `No suitable reader found for the file format of file "...glb"`, the file is a **git-lfs pointer**: run `git lfs install && git lfs pull`.
7. **Polycount targets (triangles):**

   | Part size | Example | Target |
   |---|---|---|
   | Small | fittings | < 10k |
   | Medium | grippers, sensors | < 25k |
   | Large | robot arms | < 100k |
   | Very large | enclosures | < 200k |

   Remove hidden parts, screws and threads. Share materials.
8. **Frames are ignored unless explicitly marked.** Add `xmlns:intrinsic="https://intrinsic.ai/"` to `<sdf>`, then mark each frame:
   - `<frame name="tool_frame" attached_to="gripper_body" intrinsic:create_entity="true"><pose>0 0 0.128 0 0 0</pose></frame>` creates a frame entity.
   - `<frame name="flange" attached_to="A6_link" intrinsic:create_attachment_entity="true"/>` creates an **attachment frame**, where child objects mount. It implies `create_entity`.

   Without these attributes the frame silently does not exist in the world. The hardware tutorial's `<frame name="tool_frame">` lacks the attribute.
9. **Other custom tags** (model level):
   - `<intrinsic:cartesian_limits>`, with children `intrinsic:min/max_translational_position|velocity|acceleration|jerk`, `intrinsic:max_rotational_velocity|acceleration|jerk`, and `intrinsic:control_frequency_hz`
   - `<intrinsic:ik_solver>`
   - `<intrinsic:user_data>` (needs proto `deps`)

   Joint-limit extras are `<intrinsic:acceleration>` and `<intrinsic:jerk>` inside `<limit>`.
10. **Names matter.**
    - The world object name comes from the **instance name**, not `<model name>`.
    - Entity names come from links, joints and frames, and are referenced by `entity_names` filters, ICON configs, and `attach` skills.
    - Keep names lowercase snake_case. Renaming a link breaks updates that reference it, e.g. `node_a_filter { entity_names: "gripper_body" }`.
11. **Sensors**: `<sensor type="camera">` / `type="depth_camera"` on a link, with the camera intrinsics in `<camera>`, become sensor entities. See the Orbbec SDF.
12. Pose syntax: `<pose relative_to="other_frame">x y z roll pitch yaw</pose>`, angles in **radians**. A link `<pose relative_to="joint_name"/>` places the child link at its joint (Schunk pattern).

## Templates

### Static fixture or enclosure (no joints)

```xml
<?xml version="1.0" ?>
<sdf version="1.9" xmlns:intrinsic="https://intrinsic.ai/">
  <model name="my_fixture">
    <static>true</static>
    <link name="base_link">
      <visual name="visual"><geometry><mesh><uri>visual.glb</uri></mesh></geometry></visual>
      <collision name="plate_box">
        <pose>0 0 0.01 0 0 0</pose>
        <geometry><box><size>0.40 0.30 0.02</size></box></geometry>
      </collision>
    </link>
    <frame name="place_frame" attached_to="base_link" intrinsic:create_entity="true">
      <pose>0 0 0.02 0 0 0</pose>
    </frame>
  </model>
</sdf>
```

### Dynamic workpiece (falls, can be grasped)

From the `import_new_part` tutorial. Compare with `intrinsic-omts/models/raw_stock_2x3x5/raw_stock_2x3x5.sdf`.

```xml
<?xml version="1.0" ?>
<sdf version="1.9">
  <model name="raw_stock_logo">
    <static>false</static>
    <link name="base_link">
      <inertial>
        <mass>0.450</mass>
        <inertia><ixx>0.0003</ixx><iyy>0.0005</iyy><izz>0.0006</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia>
      </inertial>
      <visual name="visual"><geometry><mesh><uri>visual.glb</uri></mesh></geometry></visual>
      <collision name="cube_collider_box">
        <pose>0 0 0 0 0 0</pose>
        <geometry><box><size>0.05 0.075 0.05</size></box></geometry>
      </collision>
    </link>
  </model>
</sdf>
```

### Articulated device (2 prismatic jaws)

Pattern of `intrinsic-omts/models/schunk_egp_64nnb/schunk_egp_64nnb.sdf`:

```xml
<sdf xmlns:intrinsic="https://intrinsic.ai/" version="1.9">
  <model name="schunk_egp_64nnb">
    <static>true</static>
    <link name="base_link"> ...visual base_visual.glb + box/cylinder collisions... </link>
    <link name="jaw_l_link"><pose relative_to="jaw_l_link_joint_prismatic"/> ...jaw_l_visual.glb... </link>
    <link name="jaw_r_link"><pose relative_to="jaw_r_link_joint_prismatic"/> ...jaw_r_visual.glb... </link>
    <joint name="jaw_l_link_joint_prismatic" type="prismatic">
      <pose relative_to="base_link">-0.01 0 0 0 0 0</pose>
      <parent>base_link</parent><child>jaw_l_link</child>
      <axis><xyz>-1 0 0</xyz><limit><lower>0.0</lower><upper>0.01</upper></limit></axis>
    </joint>
    <joint name="jaw_r_link_joint_prismatic" type="prismatic"> ...mirror, xyz 1 0 0... </joint>
    <frame name="jaw_r_frame" attached_to="base_link" intrinsic:create_entity="true"><pose>0.022 0 0.12255 0 0 0</pose></frame>
    <frame name="jaw_l_frame" attached_to="base_link" intrinsic:create_entity="true"><pose>-0.022 0 0.12255 0 0 3.141593</pose></frame>
  </model>
</sdf>
```

Joint values are set in the world via `update_object_joints { joint_positions: 0.01 joint_positions: 0.01 }`, in joint declaration order.

### End-effector (gripper body + fingers + TCP)

Pattern of the Robotiq Hand-E:

- Links `gripper_body`, `gripper_finger1` and `gripper_finger2`.
- Prismatic joints `finger1` and `finger2` (0–0.025 m).
- `<frame name="tool_frame" attached_to="gripper_body" intrinsic:create_entity="true"><pose>0 0 0.128 0 0 0</pose></frame>`

The gripper's base link must be the mounting face, so that `flange → gripper` is a simple z offset. Reuse a core model by merging it: `<include merge="true"><uri>model://intrinsic_control/.../robotiq_hande/robotiq_hande</uri></include>`.

## CAD → SDF paths

- **Mesh only (no kinematics):** export GLB, then use the static or dynamic template above.
- **Kinematics, by hand:**
  1. Export one mesh per rigid link.
  2. Write the links and joints.
  3. Take the center of mass from CAD and put it into `<inertial><pose>`.
  4. Fill in the inertia.
- **Blender + SDF_Gen add-on** (`github.com/cole-bsmr/SDF_Gen`, needs the paid STEPper add-on for STEP):
  1. Clean Mesh.
  2. Decimate.
  3. Links tab → Create Link, drag meshes into the visual collection, set Static.
  4. Create colliders (Box/Cylinder/Sphere/Cone/Plane preferred, Mesh Collider last).
  5. Joints tab → Create Armature → Create Joint (the child is fixed), then Adjust Joints, set limits, and test in Local transform space.
  6. Export as GLB with "Relative link poses" checked. Mesh colliders export as STL.
- **No Bazel at all** (runtime import from OBJ/STEP/... over gRPC): see [runtime-scene-object-import.md](./runtime-scene-object-import.md).

## Robot models

Robot SDFs are generated with xacro. For example, `intrinsic-core/intrinsic_control/intrinsic/models/robot_definitions/ur/BUILD` uses `xacro_file(name="ur5e_xacro", src="ur5e/ur5e_world.sdf.xacro", out="ur5e_world.sdf")`, then `sdf_scene_object(name="ur5e_scene_object", src="ur5e_world.sdf", updates_pbtxts=["ur.named_configurations.pbtxt", "ur5e/ur5e_limits.updates.pbtxt"])`. The default named configs (`home`) and limits are SceneObjectUpdates baked into the asset.
