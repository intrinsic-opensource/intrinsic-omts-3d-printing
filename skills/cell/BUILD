load("@com_google_protobuf//bazel:proto_library.bzl", "proto_library")
load("@com_google_protobuf//bazel:py_proto_library.bzl", "py_proto_library")
load("@intrinsic-core//bazel:python.bzl", "py_library")
load("@intrinsic-core//intrinsic_sdk/intrinsic/skills/build_defs:skill.bzl", "py_skill", "skill_manifest")

package(default_visibility = ["//visibility:public"])

proto_library(
    name = "configure_cell_proto",
    srcs = ["configure_cell.proto"],
    deps = [
        "@intrinsic_apis//intrinsic/math/proto:point_proto",
        "@intrinsic_apis//intrinsic/math/proto:pose_proto",
    ],
)

py_proto_library(
    name = "configure_cell_py_pb2",
    deps = [":configure_cell_proto"],
)

py_library(
    name = "configure_cell",
    srcs = ["configure_cell.py"],
    deps = [
        ":configure_cell_py_pb2",
        "//src/core:drop_off",
        "@intrinsic-core//intrinsic_sdk/intrinsic/math/python:data_types",
        "@intrinsic-core//intrinsic_sdk/intrinsic/math/python:proto_conversion",
        "@intrinsic-core//intrinsic_sdk/intrinsic/skills/python:skill_interface",
        "@intrinsic-core//intrinsic_sdk/intrinsic/world/proto:object_world_updates_py_pb2",
        "@intrinsic_apis//intrinsic/skills/proto:footprint_py_pb2",
        "@intrinsic_apis//intrinsic/world/proto:object_world_refs_py_pb2",
    ],
)

skill_manifest(
    name = "configure_cell_manifest",
    src = "configure_cell.manifest.textproto",
    deps = [":configure_cell_proto"],
)

py_skill(
    name = "configure_cell_skill",
    base_image = "@distroless_python3",
    manifest = ":configure_cell_manifest",
    deps = [":configure_cell"],
)
