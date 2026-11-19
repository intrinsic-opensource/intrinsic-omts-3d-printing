load("@com_google_protobuf//bazel:proto_library.bzl", "proto_library")
load("@com_google_protobuf//bazel:py_proto_library.bzl", "py_proto_library")
load("@intrinsic-core//bazel:python.bzl", "py_library")
load("@intrinsic-core//intrinsic_sdk/intrinsic/skills/build_defs:skill.bzl", "py_skill", "skill_manifest")

package(default_visibility = ["//visibility:public"])

proto_library(
    name = "register_pose_estimator_proto",
    srcs = ["register_pose_estimator.proto"],
    deps = [
        "@intrinsic_apis//intrinsic/assets/proto:field_metadata_proto",
        "@intrinsic_apis//intrinsic/assets/proto:id_proto",
        "@intrinsic_apis//intrinsic/assets/proto/v1:resolved_dependency_proto",
        "@intrinsic_apis//intrinsic/perception/proto/v1:pose_estimator_id_proto",
    ],
)

py_proto_library(
    name = "register_pose_estimator_py_pb2",
    deps = [":register_pose_estimator_proto"],
)

py_library(
    name = "train_requests",
    srcs = ["train_requests.py"],
    deps = [
        "@intrinsic-core//intrinsic_perception/intrinsic/perception/service/ioc_train_service/proto:ioc_pose_estimator_params_py_pb2",
        "@intrinsic_apis//intrinsic/assets/proto:id_py_pb2",
        "@intrinsic_apis//intrinsic/perception/proto/v1:pose_estimation_config_py_pb2",
        "@intrinsic_apis//intrinsic/perception/proto/v1:pose_range_py_pb2",
        "@intrinsic_apis//intrinsic/perception/proto/v1:target_py_pb2",
        "@intrinsic_apis//intrinsic/perception/proto/v1:train_service_py_pb2",
    ],
)

py_library(
    name = "register_pose_estimator",
    srcs = ["register_pose_estimator.py"],
    deps = [
        ":register_pose_estimator_py_pb2",
        ":train_requests",
        "@com_github_grpc_grpc//src/python/grpcio/grpc:grpcio",
        "@com_google_googleapis//google/longrunning:operations_py_proto",
        "@intrinsic-core//intrinsic_sdk/intrinsic/assets/dependencies:utils_py",
        "@intrinsic-core//intrinsic_sdk/intrinsic/assets/proto:installed_assets_pb2_grpc",
        "@intrinsic-core//intrinsic_sdk/intrinsic/assets/proto:installed_assets_py_pb2",
        "@intrinsic-core//intrinsic_sdk/intrinsic/skills/python:skill_interface",
        "@intrinsic_apis//intrinsic/assets/proto:view_py_pb2",
        "@intrinsic_apis//intrinsic/perception/proto/v1:pose_estimator_id_py_pb2",
        "@intrinsic_apis//intrinsic/perception/proto/v1:train_service_py_pb2",
        "@intrinsic_apis//intrinsic/perception/proto/v1:train_service_py_pb2_grpc",
        "@intrinsic_apis//intrinsic/skills/proto:footprint_py_pb2",
    ],
)

skill_manifest(
    name = "register_pose_estimator_manifest",
    src = "register_pose_estimator.manifest.textproto",
    deps = [":register_pose_estimator_proto"],
)

py_skill(
    name = "register_pose_estimator_skill",
    base_image = "@distroless_python3",
    manifest = ":register_pose_estimator_manifest",
    deps = [":register_pose_estimator"],
)
