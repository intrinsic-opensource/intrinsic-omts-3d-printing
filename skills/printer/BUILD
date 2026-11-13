load("@com_google_protobuf//bazel:proto_library.bzl", "proto_library")
load("@com_google_protobuf//bazel:py_proto_library.bzl", "py_proto_library")
load("@intrinsic-core//bazel:python.bzl", "py_library")
load("@intrinsic-core//intrinsic_sdk/intrinsic/skills/build_defs:skill.bzl", "py_skill", "skill_manifest")

package(default_visibility = ["//visibility:public"])

proto_library(
    name = "read_printer_status_proto",
    srcs = ["read_printer_status.proto"],
    deps = ["//services/prusalink:prusalink_proto"],
)

py_proto_library(
    name = "read_printer_status_py_pb2",
    deps = [":read_printer_status_proto"],
)

proto_library(
    name = "job_model_proto",
    srcs = ["job_model.proto"],
    deps = ["//services/prusalink:prusalink_proto"],
)

py_proto_library(
    name = "job_model_py_pb2",
    deps = [":job_model_proto"],
)

py_library(
    name = "job_model_skills",
    srcs = ["job_model_skills.py"],
    deps = [
        ":job_model_py_pb2",
        ":printer_skills",
        "//services/prusalink:prusalink_py_pb2",
        "@com_github_grpc_grpc//src/python/grpcio/grpc:grpcio",
        "@com_google_protobuf//:protobuf_python",
        "@intrinsic-core//intrinsic_sdk/intrinsic/skills/python:skill_interface",
    ],
)

py_library(
    name = "printer_skills",
    srcs = ["printer_skills.py"],
    deps = [
        ":read_printer_status_py_pb2",
        "//services/prusalink:prusalink_py_pb2",
        "//services/prusalink:prusalink_py_pb2_grpc",
        "@com_github_grpc_grpc//src/python/grpcio/grpc:grpcio",
        "@com_google_protobuf//:protobuf_python",
        "@intrinsic-core//intrinsic_sdk/intrinsic/skills/python:skill_interface",
        "@intrinsic_apis//intrinsic/skills/proto:footprint_py_pb2",
    ],
)

[
    skill_manifest(
        name = name + "_manifest",
        src = name + ".manifest.textproto",
        incompatible_disallow_manifest_dependencies = False,
        deps = [":read_printer_status_proto"],
    )
    for name in [
        "read_printer_status",
        "wait_for_printer_ready",
    ]
]

[
    py_skill(
        name = name,
        base_image = "@distroless_python3",
        manifest = ":" + name + "_manifest",
        deps = [":printer_skills"],
    )
    for name in [
        "read_printer_status",
        "wait_for_printer_ready",
    ]
]

[
    skill_manifest(
        name = name + "_manifest",
        src = name + ".manifest.textproto",
        incompatible_disallow_manifest_dependencies = False,
        deps = [":job_model_proto"],
    )
    for name in [
        "read_job_model",
        "wait_for_job_model",
    ]
]

[
    py_skill(
        name = name,
        base_image = "@distroless_python3",
        manifest = ":" + name + "_manifest",
        deps = [":job_model_skills"],
    )
    for name in [
        "read_job_model",
        "wait_for_job_model",
    ]
]
