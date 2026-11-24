# Copyright 2026 Intrinsic Innovation LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""ArUco marker detection and pose maths (numpy and OpenCV only).

No Intrinsic imports, so a skill, a host tool and hermetic tests can share it.

The marker frame is the one in src/core/door.py: origin at the marker's
centre, x to the right and y down in the image, z into the marker. The corners
come in OpenCV's order: top-left, top-right, bottom-right, bottom-left.
"""

import dataclasses
import math

import cv2
import numpy as np

DICTIONARY = cv2.aruco.DICT_4X4_50


def marker_object_points(size_m: float) -> np.ndarray:
  """Corners (4, 3) of a marker of side size_m in its own frame."""
  h = size_m / 2.0
  return np.array(
    [[-h, -h, 0.0], [h, -h, 0.0], [h, h, 0.0], [-h, h, 0.0]], dtype=np.float64
  )


@dataclasses.dataclass(frozen=True)
class Detection:
  """One accepted marker pose, camera frame."""

  marker_id: int
  rotation: np.ndarray  # camera_R_marker, (3, 3)
  translation: np.ndarray  # camera_t_marker, (3,)
  reprojection_px: float
  ippe_ratio: float  # error of the other solution / error of this one
  incidence_deg: float
  side_px: float


@dataclasses.dataclass(frozen=True)
class ViewingRule:
  """One rule for a usable detection (plan section 4)."""

  max_incidence_deg: float = 60.0
  min_side_px: float = 50.0
  max_reprojection_px: float = 1.0
  min_ippe_ratio: float = 1.0  # tuned on synthetic images, see the tests


def detect_corners(image: np.ndarray) -> dict[int, np.ndarray]:
  """Finds DICT_4X4_50 markers; id -> corners (4, 2) in pixels."""
  if image.ndim == 3:
    image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
  params = cv2.aruco.DetectorParameters()
  params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
  detector = cv2.aruco.ArucoDetector(
    cv2.aruco.getPredefinedDictionary(DICTIONARY), params
  )
  corners, ids, _ = detector.detectMarkers(image)
  if ids is None:
    return {}
  return {
    int(i): c.reshape(4, 2).astype(np.float64)
    for i, c in zip(ids.flatten(), corners, strict=True)
  }


def _reproj_error(obj, img, rvec, tvec, k, dist) -> float:
  proj, _ = cv2.projectPoints(obj, rvec, tvec, k, dist)
  d = proj.reshape(-1, 2) - img
  return float(math.sqrt((d**2).sum(axis=1).mean()))


def solve_marker(
  marker_id: int,
  corners: np.ndarray,
  size_m: float,
  k: np.ndarray,
  dist: np.ndarray | None = None,
) -> Detection:
  """Pose of one marker from its corners (IPPE, two solutions).

  The better solution is returned with the error ratio to the other one; a
  viewing rule may only reject it (see check_viewing_rule), never pick it.
  """
  dist = np.zeros(5) if dist is None else dist
  obj = marker_object_points(size_m)
  n, rvecs, tvecs, errs = cv2.solvePnPGeneric(
    obj, corners, k, dist, flags=cv2.SOLVEPNP_IPPE
  )
  if n < 1:
    raise ValueError(f"marker {marker_id}: no pose")
  errs = [
    _reproj_error(obj, corners, rvecs[i], tvecs[i], k, dist) for i in range(n)
  ]
  order = np.argsort(errs)
  best = int(order[0])
  other = float(errs[int(order[1])]) if n > 1 else float("inf")
  rot, _ = cv2.Rodrigues(rvecs[best])
  t = tvecs[best].reshape(3)
  normal = rot[:, 2]
  ray = t / np.linalg.norm(t)
  incidence = math.degrees(math.acos(float(np.clip(normal @ ray, -1, 1))))
  side = float(
    np.mean(
      [np.linalg.norm(corners[i] - corners[(i + 1) % 4]) for i in range(4)]
    )
  )
  eps = 1e-6
  return Detection(
    marker_id=marker_id,
    rotation=rot,
    translation=t,
    reprojection_px=errs[best],
    ippe_ratio=other / max(errs[best], eps),
    incidence_deg=incidence,
    side_px=side,
  )


def check_viewing_rule(det: Detection, rule: ViewingRule) -> str | None:
  """None if the detection counts, else the reason it does not."""
  if det.incidence_deg > rule.max_incidence_deg:
    return f"incidence {det.incidence_deg:.1f} deg"
  if det.side_px < rule.min_side_px:
    return f"side {det.side_px:.0f} px"
  if det.reprojection_px > rule.max_reprojection_px:
    return f"reprojection {det.reprojection_px:.2f} px"
  if det.ippe_ratio < rule.min_ippe_ratio:
    return f"ambiguous (ratio {det.ippe_ratio:.2f})"
  return None


def solve_joint(
  corners_by_id: dict[int, np.ndarray],
  object_points_by_id: dict[int, np.ndarray],
  k: np.ndarray,
  dist: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, float]:
  """One pose (camera_R_frame, camera_t_frame, rms px) from several markers.

  object_points_by_id holds each marker's four corners in the common frame
  (for example the printer's). All corners are used in one PnP, which removes
  the face-on ambiguity of a single marker (plan D23).
  """
  dist = np.zeros(5) if dist is None else dist
  ids = sorted(set(corners_by_id) & set(object_points_by_id))
  if len(ids) < 2:
    raise ValueError("joint pose needs at least two markers")
  obj = np.vstack([object_points_by_id[i] for i in ids]).astype(np.float64)
  img = np.vstack([corners_by_id[i] for i in ids]).astype(np.float64)
  ok, rvec, tvec = cv2.solvePnP(obj, img, k, dist, flags=cv2.SOLVEPNP_SQPNP)
  if not ok:
    raise ValueError("joint pose failed")
  rvec, tvec = cv2.solvePnPRefineLM(obj, img, k, dist, rvec, tvec)
  rot, _ = cv2.Rodrigues(rvec)
  return rot, tvec.reshape(3), _reproj_error(obj, img, rvec, tvec, k, dist)


def render_marker(
  image_size: tuple[int, int],
  k: np.ndarray,
  rot: np.ndarray,
  t: np.ndarray,
  marker_id: int,
  size_m: float,
  background: int = 128,
  quiet_zone: float = 0.25,
) -> np.ndarray:
  """Synthetic grayscale view of a marker at camera_T_marker (for tests).

  The marker sits on a white tile with a quiet zone (fraction of the side).
  """
  w, h = image_size
  img = np.full((h, w), background, np.uint8)
  px = 400
  marker = cv2.aruco.generateImageMarker(
    cv2.aruco.getPredefinedDictionary(DICTIONARY), marker_id, px
  )
  pad = int(px * quiet_zone)
  tile = np.full((px + 2 * pad, px + 2 * pad), 255, np.uint8)
  tile[pad : pad + px, pad : pad + px] = marker
  half = size_m / 2.0 * (1 + 2 * quiet_zone)
  obj = np.array(
    [[-half, -half, 0], [half, -half, 0], [half, half, 0], [-half, half, 0]]
  )
  rvec, _ = cv2.Rodrigues(rot)
  proj, _ = cv2.projectPoints(obj, rvec, t.reshape(3, 1), k, np.zeros(5))
  src = np.array(
    [
      [0, 0],
      [tile.shape[1] - 1, 0],
      [tile.shape[1] - 1, tile.shape[0] - 1],
      [0, tile.shape[0] - 1],
    ],
    np.float32,
  )
  m = cv2.getPerspectiveTransform(src, proj.reshape(4, 2).astype(np.float32))
  warped = cv2.warpPerspective(
    tile, m, (w, h), flags=cv2.INTER_AREA, borderValue=background
  )
  mask = cv2.warpPerspective(
    np.full_like(tile, 255), m, (w, h), flags=cv2.INTER_NEAREST
  )
  img[mask > 0] = warped[mask > 0]
  return img
