# Runtime scene-object import over gRPC (no Bazel)

Source: `sdk-examples/notebooks/011_scene_object_import.ipynb`, with spawning from `sdk-examples/notebooks/003_world.ipynb`. Use this to turn a mesh or CAD file into an installed SceneObject asset from Python against a running solution.

The result **is not in source control**. For permanent parts prefer the Bazel path (`sdf_scene_object` + `intrinsic_scene_object` + `intrinsic_solution`).

## Services

```python
from intrinsic.solutions import deployments
from intrinsic.scene.proto.v1 import scene_object_import_pb2, scene_object_import_pb2_grpc
from intrinsic.assets.proto import installed_assets_pb2, installed_assets_pb2_grpc, id_pb2, vendor_pb2, documentation_pb2
from intrinsic.assets.scene_objects.proto import scene_object_manifest_pb2
from google.longrunning import operations_pb2, operations_pb2_grpc
from google.protobuf import descriptor_pb2

solution = deployments.connect(address="localhost:17080")       # or connect_to_selected_solution()
ch = solution.grpc_channel
importer = scene_object_import_pb2_grpc.SceneObjectImportStub(ch)
installed = installed_assets_pb2_grpc.InstalledAssetsStub(ch)
ops = operations_pb2_grpc.OperationsStub(ch)

def wait(op):                       # both RPCs return google.longrunning.Operation
    while not op.done:
        time.sleep(1); op = ops.GetOperation(operations_pb2.GetOperationRequest(name=op.name))
    if op.HasField("error"): raise RuntimeError(op.error)
    return op
```

## 1. Import a file → SceneObject

```python
req = scene_object_import_pb2.ImportSceneObjectRequest(
    file=scene_object_import_pb2.SceneFileData(data=open("part.obj","rb").read(),
                                               file_type=scene_object_import_pb2.SceneFileData.Type.OBJ),  # also STEP, ...
    config=scene_object_import_pb2.ImportSceneObjectConfig(
        scene_object_name="my_part",
        length_unit_conversion=scene_object_import_pb2.LengthUnitConversion(scale_factor=0.0254),  # inches→m
        # geometry_operations=scene_object_import_pb2.GeometryOperations(remove_types=["Intrinsic_Collision"]),
        # material_properties=material_pb2.MaterialProperties(base_color=color_pb2.Color(red=1), metalness=1, roughness=0),
        # user_data={"key": any_pb2.Any(...)},       # then pass the FileDescriptorSet at install
        # then: config.transform_scene_object.translation.x = -centroid.x  (y, z likewise) to center the part
    ))
resp = scene_object_import_pb2.ImportSceneObjectResponse()
wait(importer.ImportSceneObject(req)).response.Unpack(resp)
so = resp.scene_object            # resp.visual_stats / resp.collision_stats: closed, volumetric_centroid, vertex_centroid...
```

By default the import generates both `Intrinsic_Visual` and `Intrinsic_Collision` geometry, with the collision geometry equal to the visual. A STEP import yields one link entity.

## 2. Install as an asset

```python
manifest = scene_object_manifest_pb2.ProcessedSceneObjectManifest(
    metadata=scene_object_manifest_pb2.SceneObjectMetadata(
        id=id_pb2.Id(package="com.example", name="my_part"),        # name: alnum + '_' , starts with a letter
        display_name="My part", vendor=vendor_pb2.Vendor(display_name="Example"),
        documentation=documentation_pb2.Documentation(description="Imported")),
    assets=scene_object_manifest_pb2.ProcessedSceneObjectAssets(
        scene_object_model=so, file_descriptor_set=descriptor_pb2.FileDescriptorSet()))
op = installed.CreateInstalledAsset(installed_assets_pb2.CreateInstalledAssetRequest(
    asset=installed_assets_pb2.CreateInstalledAssetRequest.Asset(scene_object=manifest),
    policy=installed_assets_pb2.UpdatePolicy.UPDATE_POLICY_ADD_NEW_ONLY))
asset = installed_assets_pb2.InstalledAsset(); wait(op).response.Unpack(asset)
```

## 3. Put it in the world

- **As an instance**, visible after reset: `inctl service add com.example.my_part --name my_part --address localhost:17080`, then `inctl world reset --address localhost:17080`.
- **Directly into belief**, transient: call `world.create_object(object_name="my_part_1", geometry_spec=so, parent=world.root, parent_object_t_created_object=data_types.Pose3(translation=[0.4, 0, 1.1]), user_data={...})`. To spawn from an already-installed asset, fetch it with `GetInstalledAsset(..., view=ASSET_VIEW_TYPE_FULL)` and use `.deployment_data.scene_object.manifest.assets.scene_object_model`.
- **During a process**: use the `create_object` skill (`ai.intrinsic.create_object`). Its parameters include `object_to_create` (asset Id), `poses[]`, `create_at_frame`, `attach_to_create_at_frame` and `object_naming_schema`.
- **Delete**: `world.delete_object(world.get_object("my_part_1"))`, or filter `world.list_objects()` by `user_data`.
