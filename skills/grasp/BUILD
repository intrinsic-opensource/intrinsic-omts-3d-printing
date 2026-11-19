load("@com_google_protobuf//bazel:proto_library.bzl", "proto_library")
load("@com_google_protobuf//bazel:py_proto_library.bzl", "py_proto_library")
load("@intrinsic-core//bazel:python.bzl", "py_library")
load("@intrinsic-core//intrinsic_sdk/intrinsic/skills/build_defs:skill.bzl", "py_skill", "skill_manifest")

package(default_visibility = ["//visibility:public"])

proto_library(
    name = "plan_cuboid_grasp_proto",
    srcs = ["plan_cuboid_grasp.proto"],
    deps = ["@intrinsic_apis//intrinsic/math/proto:pose_proto"],
)

py_proto_library(
    name = "plan_cuboid_grasp_py_pb2",
    deps = [":plan_cuboid_grasp_proto"],
)

py_library(
    name = "plan_cuboid_grasp",
    srcs = ["plan_cuboid_grasp.py"],
    deps = [
        ":plan_cuboid_grasp_py_pb2",
        "//src/core:grasp_math",
        "@intrinsic-core//intrinsic_sdk/intrinsic/math/python:data_types",
        "@intrinsic-core//intrinsic_sdk/intrinsic/math/python:proto_conversion",
        "@intrinsic-core//intrinsic_sdk/intrinsic/skills/python:skill_interface",
        "@intrinsic_apis//intrinsic/skills/proto:footprint_py_pb2",
    ],
)

skill_manifest(
    name = "plan_cuboid_grasp_manifest",
    src = "plan_cuboid_grasp.manifest.textproto",
    deps = [":plan_cuboid_grasp_proto"],
)

py_skill(
    name = "plan_cuboid_grasp_skill",
    base_image = "@distroless_python3",
    manifest = ":plan_cuboid_grasp_manifest",
    deps = [":plan_cuboid_grasp"],
)
