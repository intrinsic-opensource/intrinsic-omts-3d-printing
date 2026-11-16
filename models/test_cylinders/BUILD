load("@intrinsic-core//intrinsic/scene/build_defs:sdf_scene_object.bzl", "sdf_scene_object")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl", "intrinsic_scene_object")

package(default_visibility = ["//visibility:public"])

# Test cylinders for the graspability trials (research/tools/README.md),
# deployed with //:rebot_solution only under --//:test_parts.
# Generated: a cylinder mesh (OBJ), used for collision too, with a 1 mm flat
# along its +x side so it does not roll when lying on the bed.

sdf_scene_object(
    name = "test_cylinder_30x60_sdf",
    src = "test_cylinder_30x60.sdf",
    sdf_assets = [
        "test_cylinder_30x60.mtl",
        "test_cylinder_30x60.obj",
    ],
)

intrinsic_scene_object(
    name = "test_cylinder_30x60",
    manifest = "test_cylinder_30x60_manifest.textproto",
    scene_object = ":test_cylinder_30x60_sdf",
)
