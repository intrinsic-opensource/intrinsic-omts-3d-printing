load("@intrinsic-core//intrinsic/scene/build_defs:sdf_scene_object.bzl", "sdf_scene_object")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl", "intrinsic_scene_object")

package(default_visibility = ["//visibility:public"])

# A low-poly 3DBenchy for the graspability trials (research/tools/README.md),
# deployed with //:rebot_solution only under --//:test_parts (README.md).

sdf_scene_object(
    name = "test_benchy_sdf",
    src = "test_benchy.sdf",
    sdf_assets = ["test_benchy.stl"],
)

intrinsic_scene_object(
    name = "test_benchy",
    manifest = "test_benchy_manifest.textproto",
    scene_object = ":test_benchy_sdf",
)
