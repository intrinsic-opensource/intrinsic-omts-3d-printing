load("@com_google_protobuf//bazel:proto_library.bzl", "proto_library")
load("@com_google_protobuf//bazel:py_proto_library.bzl", "py_proto_library")
load("@intrinsic-core//bazel:python.bzl", "py_library")
load("@intrinsic-core//intrinsic_sdk/intrinsic/skills/build_defs:skill.bzl", "py_skill", "skill_manifest")

package(default_visibility = ["//visibility:public"])

py_library(
    name = "arc_math",
    srcs = ["arc_math.py"],
    deps = ["@ai_intrinsic_sdks_pip_deps//numpy"],
)

proto_library(
    name = "generate_arc_frames_proto",
    srcs = ["generate_arc_frames.proto"],
    deps = ["@intrinsic_apis//intrinsic/world/proto:object_world_refs_proto"],
)

py_proto_library(
    name = "generate_arc_frames_py_pb2",
    deps = [":generate_arc_frames_proto"],
)

py_library(
    name = "arc_frames_skill",
    srcs = ["arc_frames_skill.py"],
    deps = [
        ":arc_math",
        ":generate_arc_frames_py_pb2",
        "@ai_intrinsic_sdks_pip_deps//numpy",
        "@com_github_grpc_grpc//src/python/grpcio/grpc:grpcio",
        "@intrinsic-core//intrinsic_sdk/intrinsic/math/python:data_types",
        "@intrinsic-core//intrinsic_sdk/intrinsic/math/python:proto_conversion",
        "@intrinsic-core//intrinsic_sdk/intrinsic/skills/python:skill_interface",
        "@intrinsic-core//intrinsic_sdk/intrinsic/world/proto:object_world_updates_py_pb2",
        "@intrinsic_apis//intrinsic/skills/proto:footprint_py_pb2",
        "@intrinsic_apis//intrinsic/world/proto:object_world_refs_py_pb2",
    ],
)

# No equipment, so the manifest needs no skill_manifest_deps allowlist entry
# (bazel/patches/printer_skill_dependencies.patch).
skill_manifest(
    name = "generate_arc_frames_manifest",
    src = "generate_arc_frames.manifest.textproto",
    deps = [":generate_arc_frames_proto"],
)

py_skill(
    name = "generate_arc_frames",
    base_image = "@distroless_python3",
    manifest = ":generate_arc_frames_manifest",
    deps = [":arc_frames_skill"],
)
