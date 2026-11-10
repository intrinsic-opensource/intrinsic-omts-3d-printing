# Python world API (SBL `solution.world`, skills `context.object_world`)

Source:

- `intrinsic-core/intrinsic_sdk/intrinsic/world/python/object_world_client.py` (class `ObjectWorldClient`)
- `intrinsic-core/intrinsic_sdk/intrinsic/solutions/worlds.py` (class `ObjectWorld(ObjectWorldClient)` with `connect()`, plus `EditWorldId`)
- Resources (WorldObject, KinematicObject, Frame, TransformNode): `intrinsic-core/intrinsic_sdk/intrinsic/world/python/object_world_resources.py`
- Examples: `sdk-examples/notebooks/003_world.ipynb`, `sdk-examples/skills/use_world/use_world.py`, `intrinsic-omts/tools/world/*.py`

## Connecting

```python
from intrinsic.solutions import deployments, worlds
from intrinsic.math.python import data_types

solution = deployments.connect(address="localhost:17080")   # Intrinsic Core (local cluster)
# solution = deployments.connect_to_selected_solution()      # Flowstate / sdk-examples notebooks
world = solution.world                                       # BELIEF world, id "world"

# Initial world (what `inctl world reset` restores). Edits here survive resets but NOT redeploys.
init_world = worlds.ObjectWorld.connect(worlds.EditWorldId.INITIAL, solution.grpc_channel)  # "init_world"
```

`worlds.EditWorldId` has two values: `INITIAL = "init_world"` and `BELIEF = "world"`. The Gazebo world `"sim_world"` is managed by the simulator. Use `solution.simulator.reset()` to re-clone belief → sim. In a skill, use `world = context.object_world`.

## Accessing nodes

| Expression | Returns |
|---|---|
| `world.<object_name>` | Object (via `__getattr__`) |
| `world.<global_frame>` | A frame on `root` |
| `world.<object>.<frame>` | A frame on that object, e.g. `world.ur_module.flange`, `world.gripper.tool_frame` |
| `world.root` | The world origin object |
| `world.get_object("name")` / `world.get_kinematic_object("name")` | Object / kinematic object |
| `world.get_frame("frame_name", "object_name")` | Frame; **frame first, object second** |
| `world.get_transform_node(ref)` | Object or frame |
| `print(world)` | Tree; `=>` marks child objects, `->` marks child frames |
| `world.list_objects()` / `world.list_object_names()` | All objects |
| `obj.frames` / `obj.frame_names` | Frames of an object |
| `obj.parent_name` / `obj.parent_t_this` | Parent and local pose |
| `robot.joint_positions` / `robot.joint_configurations.home.joint_position` | Kinematic state |

Compare `TransformNode`s by `.id`. `==` is not implemented.

## Method signatures (ObjectWorldClient)

```python
list_object_names() -> list[WorldObjectName]
list_objects(query_objects=None) -> list[WorldObject]
get_object(object_reference) -> WorldObject
get_kinematic_object(object_reference) -> KinematicObject
get_frame(frame_reference, object_name=None) -> Frame
get_transform(node_a, node_b) -> data_types.Pose3                     # a_t_b
update_transform(node_a, node_b, a_t_b: Pose3, node_to_update=None) -> None
update_object_name(object_to_update, new_name, *, name_is_global_alias=None)
update_frame_name(frame_to_update, new_name)
update_joint_positions(kinematic_object, joint_positions: list[float], joint_names=None)  # radians / meters
update_joint_application_limits(kinematic_object, joint_limits: JointLimitsUpdate)
update_joint_system_limits(kinematic_object, joint_limits: JointLimitsUpdate)
update_kinematic_object_joint_configurations(kinematic_object,
    named_joint_configurations_to_remove=None, named_joint_configurations_to_set=None)  # NamedJointConfiguration
update_kinematic_object_cartesian_limits(kinematic_object, limits: CartesianLimits)
update_kinematic_object_payload(kinematic_object, payload: RobotPayload)
reparent_object(child_object, new_parent: WorldObject | Frame)        # to an object -> attaches to its BASE entity
reparent_object_to(child_object, new_parent, entity_filter: ObjectEntityFilter)
reparent_object_to_final_entity(child_object, new_parent: KinematicObject)  # mount on flange link
disable_collisions(first_object, second_object, *, first_entity_filter=ALL, second_entity_filter=ALL)
enable_collisions(first_object, second_object, *, ...)
delete_object(world_object, *, force=False, reparent_child_objects=False)
delete_frame(frame, *, force=False)
create_frame(frame_name, parent: TransformNode | None = None, parent_t_frame: Pose3 = Pose3()) -> Frame
reparent_frame(frame, parent: TransformNode)
create_object(*, object_name, geometry_spec: SceneObject | GeometryComponent, parent=None,
              parent_object_t_created_object: Pose3 = Pose3(), user_data=None)
create_geometry_object(*, object_name, geometry_component, parent=None, parent_object_t_created_object=Pose3(), user_data=None)
register_geometry_v1(*, geometry: CreateGeometryRequest)      # use v1, not register_geometry (v0 refs)
batch_update(updates: object_world_updates_pb2.ObjectWorldUpdates) -> None   # apply a whole .pbtxt
reset() -> None                                                # restore belief world from init_world
clone() -> ContextManager[ObjectWorldClient]                   # sandbox world, auto-deleted
```

## Common recipes

```python
# Move an object 1 cm above a frame, rewriting the object's own parent pose:
world.update_transform(world.target_right, world.building_block0,
                       data_types.Pose3(translation=[0, 0, 0.01]), world.building_block0)

# Create a global frame:
world.create_frame("capture", world.root,
                   data_types.Pose3(translation=[0.3, 0, 1.2],
                                    rotation=data_types.Rotation3.from_euler_angles(rpy_degrees=[180, 0, 0])))

# Mount an object on the robot flange link:
world.reparent_object_to_final_entity(world.camera_mount, world.get_kinematic_object("ur_module"))

# Apply a .pbtxt file to the live world (what apply_scene_updates does, minus create_frame→update adaptation):
from google.protobuf import text_format
from intrinsic.world.proto import object_world_updates_pb2
ups = text_format.Parse(open("configs/omts/scene.updates.pbtxt").read(),
                        object_world_updates_pb2.ObjectWorldUpdates())
world.batch_update(ups)
init_world.batch_update(ups)        # optional: also survive `inctl world reset`

# Spawn an installed SceneObject asset (notebook 003):
from intrinsic.assets.proto import installed_assets_pb2, installed_assets_pb2_grpc, id_pb2, view_pb2
stub = installed_assets_pb2_grpc.InstalledAssetsStub(solution.grpc_channel)
asset = stub.GetInstalledAsset(installed_assets_pb2.GetInstalledAssetRequest(
    id=id_pb2.Id(package="ai.intrinsic", name="building_block"),
    view=view_pb2.AssetViewType.ASSET_VIEW_TYPE_FULL))
world.create_object(object_name="block_1",
    geometry_spec=asset.deployment_data.scene_object.manifest.assets.scene_object_model)
```

## Pose types (`intrinsic.math.python.data_types`)

- `Pose3(rotation=Rotation3(...), translation=[x, y, z])`
- `Pose3.from_vec7([tx, ty, tz, qx, qy, qz, qw])` and `pose.vec7`
- `Rotation3(Quaternion([qx, qy, qz, qw]))` and `Rotation3.from_euler_angles(rpy_degrees=[r, p, y])`
- Compose poses with `a_t_b * b_t_c`. Use `pose.inverse()`.

## Persistence matrix

| Where you wrote | Survives `inctl world reset` | Survives solution redeploy |
|---|---|---|
| `world` (belief) only | no | no |
| `world` + `init_world` | yes | no |
| `.updates.pbtxt` listed in `intrinsic_solution(object_world_updates=...)` | yes (after redeploy) | yes |
| SceneObjectUpdates in the asset (`sdf_scene_object(updates_pbtxts=...)`) | yes | yes (every instance) |

Low-level gRPC alternative: `ObjectWorldService/SyncObject(from_world_id="world", to_world_id="init_world", object=...)` copies one object's state to the initial world. See `intrinsic-core/.agents/skills/intrinsic-core-api-overview/references/world-and-kinematics.md` §2.3.

## Simulation sync

Live edits to `world` do **not** move things in Gazebo until the simulator re-clones the belief world. Use one of:

- `solution.simulator.reset()` in Python
- `apply_scene_updates --reset_sim` (default on)
- `inctl world reset`, which resets belief to init **and** restarts the simulation

ICON/Gazebo stream sensed joint positions into `world` at ~50 Hz while running, so a joint update made early in a batch can be overwritten. `apply_scene_updates` re-applies joint updates right before `simulator.reset()` for this reason. On a **real** deployment it skips `update_object_joints`/`update_object_joint` entirely, because the sensed robot state wins.
