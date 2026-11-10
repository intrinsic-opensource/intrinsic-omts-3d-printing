load("@com_github_grpc_grpc//bazel:python_rules.bzl", "py_grpc_library")
load("@com_google_protobuf//bazel:proto_library.bzl", "proto_library")
load("@com_google_protobuf//bazel:py_proto_library.bzl", "py_proto_library")
load("@intrinsic-core//bazel:python.bzl", "py_binary", "py_library")
load("@intrinsic-core//bazel:python_oci_image.bzl", "python_oci_image")
load("@intrinsic-core//intrinsic/assets/build_defs:solution.bzl", "intrinsic_solution")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/build_defs:asset.bzl", "intrinsic_asset_instance")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/services/build_defs:services.bzl", "intrinsic_service")

package(default_visibility = ["//visibility:public"])

proto_library(
    name = "prusalink_proto",
    srcs = ["prusalink.proto"],
    deps = [
        "@com_google_protobuf//:empty_proto",
        "@com_google_protobuf//:timestamp_proto",
    ],
)

py_proto_library(
    name = "prusalink_py_pb2",
    deps = [":prusalink_proto"],
)

py_grpc_library(
    name = "prusalink_py_pb2_grpc",
    srcs = [":prusalink_proto"],
    deps = [":prusalink_py_pb2"],
)

py_library(
    name = "client",
    srcs = ["client.py"],
    deps = [":prusalink_py_pb2"],
)

py_library(
    name = "mock",
    srcs = ["mock.py"],
    deps = [":client"],
)

py_library(
    name = "server",
    srcs = ["server.py"],
    deps = [
        ":client",
        ":mock",
        ":prusalink_py_pb2",
        ":prusalink_py_pb2_grpc",
        "@com_github_grpc_grpc//src/python/grpcio/grpc:grpcio",
        "@com_google_protobuf//:protobuf_python",
    ],
)

py_library(
    name = "main_lib",
    srcs = ["main.py"],
    deps = [
        ":client",
        ":mock",
        ":prusalink_py_pb2",
        ":server",
        "@com_google_protobuf//:protobuf_python",
        "@intrinsic_apis//intrinsic/resources/proto:runtime_context_py_pb2",
    ],
)

py_binary(
    name = "prusalink_server",
    srcs = ["main.py"],
    main = "main.py",
    deps = [":main_lib"],
)

python_oci_image(
    name = "prusalink_image",
    base = "@distroless_python3",
    binary = ":prusalink_server",
    cmd = [],
    data_path = "/",
    entrypoint = [
        "/usr/bin/python3",
        "-u",
        "/services/prusalink/prusalink_server",
    ],
)

intrinsic_service(
    name = "prusalink_service",
    default_config = "default_config.textproto",
    images = [":prusalink_image.tar"],
    manifest = "prusalink_service_manifest.textproto",
    deps = [":prusalink_proto"],
)

intrinsic_asset_instance(
    name = "prusalink_instance",
    asset = "ai.omts.prusalink",
    instance_name = "prusalink",
    service_config = "simulation_config.textproto",
)

intrinsic_solution(
    name = "prusalink_solution",
    assets = [":prusalink_service"],
    default_operation_mode = "sim",
    instances = [":prusalink_instance"],
)
