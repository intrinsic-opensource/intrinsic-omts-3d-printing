# ObjectWorldUpdates reference (`*.updates.pbtxt`)

This is a source-verified reference. Proto paths are relative to `/home/berti/gits/`.

- Message definitions: `intrinsic-core/intrinsic_sdk/intrinsic/world/proto/object_world_updates.proto`
- Reference types: `intrinsic-core/intrinsic_apis/intrinsic/world/proto/object_world_refs.proto`
- Working examples: `intrinsic-omts/configs/omts/*.updates.pbtxt` and `intrinsic-omts/configs/lab_bb_01/*.updates.pbtxt`

## File header (always include)

```textproto
# proto-file: intrinsic/world/public/proto/object_world_updates.proto
# proto-message: intrinsic_proto.world.ObjectWorldUpdates
```

The top-level message is `ObjectWorldUpdates { repeated ObjectWorldUpdate updates = 1; }`. Each `updates { ... }` block holds exactly one entry of the `update` oneof. Text-format rules:

- `updates { ... }` and `updates: { ... }` are equivalent, and the colon is optional before `{`.
- Repeated scalars are written by repeating the key: `joint_positions: 0.4` on one line, `joint_positions: 0.01` on the next.
- Comments start with `#`.
- Updates run **in file order**. Files run **in the order listed** in `intrinsic_solution(object_world_updates=...)` or `--files`. A later update overrides an earlier one.
- Every `world_id` field is left unset in files. The deploy step or tool supplies the world.

## The `update` oneof (all variants)

| Field | Request message | Typical use |
|---|---|---|
| `create_object` | `CreateObjectRequest` | Spawn an object from a SceneObject, a single entity, or a clone. |
| `delete_object` | `DeleteObjectRequest` | Remove an object (`force` = also delete children; `reparent_child_objects`). |
| `update_object_name` | `UpdateObjectNameRequest` | Rename an object. |
| `update_object_joints` | `UpdateObjectJointsRequest` | Set joint positions and/or application/system limits of a kinematic object. |
| `update_object_joint` | `UpdateObjectJointRequest` | Set a single named joint. |
| `update_kinematic_object_properties` | `UpdateKinematicObjectPropertiesRequest` | Named joint configs, cartesian limits, mounted payload, kinematics; also used to refresh kinematic properties after mounting tools. |
| `update_object_properties` | `UpdateObjectPropertiesRequest` | `simulation_component` (`is_static`, `disabled`), geometry option overrides, user data. |
| `update_entity_properties` | `UpdateEntityPropertiesRequest` | Geometry component and geometry option overrides of one entity. |
| `update_collision_settings` | `UpdateCollisionSettingsRequest` | World-wide collision settings (`disable_collision_checking`, `minimum_margin`). |
| `create_frame` | `CreateFrameRequest` | Add a named frame under an object, entity, or frame. |
| `delete_frame` | `DeleteFrameRequest` | Remove a frame (`force` = also delete child frames). |
| `update_frame_name` | `UpdateFrameNameRequest` | Rename a frame. |
| `reparent_frame` | `ReparentFrameRequest` | Move a frame under another object entity or frame. |
| `update_frame_properties` | `UpdateFramePropertiesRequest` | `is_attachment_frame` (BoolValue). |
| `update_transform` | `UpdateTransformRequest` | Set the pose between two nodes (objects or frames). |
| `reparent_object` | `ReparentObjectRequest` | Attach an object to another object entity or frame, e.g. a gripper on the flange. |
| `toggle_collisions` | `ToggleCollisionsRequest` | Enable or disable collisions between entities of two objects. |

## Reference types

```text
ObjectReference                 { id | by_name { object_name } ; debug_hint }
FrameReference                  { id | by_name { object_name, frame_name } ; debug_hint }
TransformNodeReference          { id | by_name { object { object_name } | frame { object_name, frame_name } } }
ObjectReferenceWithEntityFilter { reference: ObjectReference, entity_filter: ObjectEntityFilter }
ObjectEntityFilter              { include_base_entity, include_final_entity, include_all_entities,
                                  entity_references[], entity_names[] }
```

- The world origin object is named `"root"`. Global frames are frames whose object is `root` and are accessed as `world.<frame>` in Python.
- **Final entity:** `include_final_entity: true` resolves to the last link of a kinematic chain, i.e. the robot flange link. It **fails** if the object has more than one leaf link. For example, `gripper` has two leaf links (`gripper_finger1` and `gripper_finger2`) and errors with `"gripper" has multiple final entities`. In that case use `entity_names: "gripper_body"`, or target an object with a single chain such as the arm. (The `attach_object_to_robot` skill failed the same way at core 20261012.0. At the OMTS core pin c40e02a, passing a gripper attaches the object to the gripper's base entity, and passing a robot attaches it to the robot's flange.)

## Pose format

`intrinsic_proto.Pose { position { x y z }  orientation { x y z w } }`. Units are meters, and the quaternion order is **x y z w**.

- Proto3 defaults omitted fields to 0, so `orientation { x: 1.0 }` means the quaternion (1,0,0,0), a 180° rotation about X. **Always write `w` explicitly** for identity (`w: 1`).
- OMTS writes `orientation { x: 0.7071 z: 0.7071 }` (w = 0). That is valid but easy to misread.
- Convert Euler angles to a quaternion with `data_types.Rotation3.from_euler_angles(rpy_degrees=[r,p,y]).quaternion` in Python, or the online converter linked by the tutorial.
- Naming: `a_t_b` is the pose of b expressed in a. `parent_t_new_frame` is the pose of the new frame in its parent.

## Templates

### create_frame (global frame on root)

```textproto
updates {
  create_frame {
    new_frame_name: "capture"
    parent_object_with_filter { reference { by_name { object_name: "root" } } }
    parent_t_new_frame {
      position { x: 0.3 y: 0.0 z: 1.2 }
      orientation { x: 0 y: 0 z: 0 w: 1 }
    }
  }
}
```

Other `attach_to` options:

- `parent_frame { by_name { object_name: "gripper" frame_name: "tool_frame" } }` puts the new frame under an existing frame.
- `parent_object_with_filter { reference {...} entity_filter { entity_names: "base_link" } }` targets a specific entity.
- `parent_object` (deprecated).

Set `designate_as_attachment_frame: true` to make it an attachment frame.

**Gotcha:** `create_frame` **fails if the frame name already exists** under that object. OMTS `apply_scene_updates` converts an existing `create_frame` into an `update_transform` automatically. Plain `batch_update` does not.

### update_transform (move an object or frame)

```textproto
updates {
  update_transform {
    node_a { by_name { object { object_name: "root" } } }
    node_b { by_name { object { object_name: "ur_module" } } }
    node_to_update { by_name { object { object_name: "ur_module" } } }
    a_t_b {
      position { x: 0.5 y: -0.3 z: 1.0 }
      orientation { x: 0 y: 0 z: -0.707 w: 0.707 }
    }
  }
}
```

Semantics:

- `node_to_update` is the node whose parent→self pose is rewritten so that the final pose from `node_a` to `node_b` equals `a_t_b`.
- `node_to_update` may be omitted only if `node_a` and `node_b` are direct neighbors in the tree. If they are not neighbors you **must** set it, or you get INVALID_ARGUMENT.
- It must not be an ancestor of both nodes.
- `update_transform` **never changes parentage**. It only changes a local pose. To attach, use `reparent_object`.
- Optional `node_a_filter` and `node_b_filter` (`ObjectEntityFilter`) pick an entity inside an object. This is required when the object would otherwise resolve ambiguously; see the tool_frame example below.

Frame-to-frame, for example mounting relative to a flange:

```textproto
node_a { by_name { frame { object_name: "ur_module" frame_name: "flange" } } }
node_b { by_name { object { object_name: "gripper" } } }
node_to_update { by_name { object { object_name: "gripper" } } }
```

### reparent_object (mount a tool or camera on the robot)

```textproto
updates {
  reparent_object {
    object { by_name { object_name: "gripper" } }
    parent_object {                       # preferred; 'new_parent' (same shape) is DEPRECATED but still used by OMTS
      reference { by_name { object_name: "ur_module" } }
      entity_filter { include_final_entity: true }   # = flange link of the arm
    }
  }
}
```

The alternative is `parent_frame { by_name { object_name: "ur_module" frame_name: "flange" } }`, which attaches to a frame. That frame is typically an attachment frame.

### Full tool mount pattern (verbatim logic of `intrinsic-omts/configs/omts/ur_module.attachments.updates.pbtxt`)

1. `update_object_joints` sets the robot start joints.
2. `update_transform` sets flange → `gripper` to `z: 0.064`. This positions the gripper object relative to the flange.
3. `update_transform` sets `gripper` → `gripper/tool_frame` to `z: 0.155` with `node_a_filter { entity_names: "gripper_body" }`, the TCP offset.
4. `reparent_object` attaches `gripper` to `ur_module` with `include_final_entity`.
5. `update_kinematic_object_properties { object { by_name { object_name: "ur_module" } } }`, with no other fields. OMTS always issues this after mounting a tool on the robot (`ur_module.attachments`, `camera_mount`). Keep it: it refreshes the robot's kinematic-object properties with the new attachment. This is our interpretation; the proto doesn't document an empty update.

Order matters: position first, then reparent, so the relative pose is kept. The camera mount uses the same pattern (`camera_mount.updates.pbtxt`, `orbbec_gemini.updates.pbtxt`).

### update_object_joints (positions and limits)

```textproto
updates {
  update_object_joints {
    object { by_name { object_name: "ur_module" } }
    joint_positions: 3.140      # one value per joint, kinematic order
    joint_positions: -1.5707
    # ... 6 values for a 6-DoF arm; 1 for cnc_enclosure door (0.4 = open); 2 for schunk vise jaws (0.01, 0.01)
  }
}
```

- **Units: radians for revolute joints, meters for prismatic joints.** The proto comment says "degrees", but that is stale. The Python client docstring and every working OMTS file use radians (e.g. `3.140`, `-1.5707`).
- `joint_names: "..."` (repeated) optionally fixes the ordering.
- Limits use `joint_application_limits` / `joint_system_limits` of type `intrinsic_proto.JointLimitsUpdate`, with fields `min_position { values: ... }` and `max_position { values: ... }` (one per joint), and similarly velocity/acceleration/jerk/effort. **A limit field is replaced as a whole**, so list every joint. See `intrinsic-omts/configs/omts/ur_module.limits.updates.pbtxt`.

Single joint:

```textproto
updates { update_object_joint { object { by_name { object_name: "cnc_enclosure" } } joint_name: "<joint>" joint_position: 0.4 } }
```

### update_kinematic_object_properties (named joint configurations, persistable)

```textproto
updates {
  update_kinematic_object_properties {
    object { by_name { object_name: "ur_module" } }
    named_joint_configurations_to_set {
      name: "home"
      joint_positions: 0.0
      joint_positions: -1.5707
      joint_positions: 1.5707
      joint_positions: -1.5707
      joint_positions: -1.5707
      joint_positions: 0.0
    }
    # named_joint_configurations_to_remove: "old_pose"
  }
}
```

This is how to **persist** a joint configuration in source. The `store_joint_config` tool writes only to the live world and init_world, never to a file.

### update_object_properties (static or disabled in simulation)

```textproto
updates {
  update_object_properties {
    object { by_name { object_name: "my_fixture" } }
    simulation_component { is_static: true }   # don't fall under gravity in Gazebo; 'disabled: true' removes from sim
  }
}
```

### toggle_collisions

```textproto
updates {
  toggle_collisions {
    toggle_mode: TOGGLE_MODE_DISABLE          # or TOGGLE_MODE_ENABLE (UNSPECIFIED = error)
    object_a { reference { by_name { object_name: "gripper" } } entity_filter { include_all_entities: true } }
    object_b { reference { by_name { object_name: "raw_stock_2x3x5" } } entity_filter { include_all_entities: true } }
  }
}
```

### delete_frame / delete_object / renames

```textproto
updates { delete_frame { frame { by_name { object_name: "root" frame_name: "capture" } } force: false } }
updates { delete_object { object { by_name { object_name: "raw_stock_logo" } } force: true } }
updates { update_frame_name { frame { by_name { object_name: "root" frame_name: "old" } } name: "new" } }
updates { update_object_name { object { by_name { object_name: "old" } } name: "new" } }
```

### create_object (spawn from a SceneObject proto)

Fields:

- `name`
- `parent_object` (with entity filter; **must** match exactly one entity)
- `parent_object_t_created_object`
- the `object_spec` oneof: `create_single_entity_object`, `clone_from_existing_object`, or `create_from_scene_object { scene_object: <intrinsic_proto.scene_object.v1.SceneObject> }`
- `user_data`
- `name_is_global_alias`

In practice create objects either by declaring an asset instance (persistent; see the hardware skill) or with `world.create_object(...)` in Python or the `create_object` skill. Do not paste SceneObject protos into pbtxt files.

## Asset-level updates are a different proto: `SceneObjectUpdates`

`sdf_scene_object(updates_pbtxts=[...])` and `scene_object(updates_pbtxts=[...])` post-process the **asset geometry at build time**. They do not touch the world.

- Header: `# proto-file: intrinsic/scene/proto/v1/scene_object_updates.proto` / `# proto-message: intrinsic_proto.scene_object.v1.SceneObjectUpdates`
- Proto: `intrinsic-core/intrinsic_apis/intrinsic/scene/proto/v1/scene_object_updates.proto`

The `update` oneof:

| Variant | Fields |
|---|---|
| `entity_pose` | `entity_name`, `parent_t_this` |
| `create_frame` | `parent_name`, `new_frame_name`, `parent_t_new_frame`, `designate_as_attachment_frame` |
| `delete_entity` | `entity_name`, `child_policy` |
| `set_named_configurations` | `named_configurations_to_set { name, joint_positions { key: "<joint>" value: <rad> } }`, keyed by joint name |
| `update_joints` | maps keyed by joint name: `joint_positions`, `joint_application_limits`, `joint_system_limits`, `parent_t_inboard` |
| `cartesian_limits` | |
| `rename_entity` | |
| `update_collision_rules` | |
| `update_user_data` | |
| `set_ik_solvers` | |
| `reparent_entity` | `entity_name`, `new_parent_name` |
| `update_frame_properties` | |
| `update_geometry` | |
| `update_physics_properties` | `entity_name`, `mass_kg`, `this_t_center_of_mass`, `inertia`, `friction`, ... |
| `create_joint` | |

Real examples are `intrinsic-core/intrinsic_control/intrinsic/models/robot_definitions/ur/ur.named_configurations.pbtxt` (named "home" pose) and `.../ur5e/ur5e_limits.updates.pbtxt`.

Use SceneObjectUpdates when the change belongs to **every instance of the part**, e.g. a default named pose or a fixed TCP frame. Use ObjectWorldUpdates when it belongs to **this cell**, e.g. placement, mounting, or cell-specific limits.
