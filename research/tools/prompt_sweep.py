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

"""Scores SAM 3 text prompts on camera images, offline, on the CPU.

Runs the pose estimator's SAM 3 export (the ONNX files in
NVIDIA_POSE_ESTIMATOR_MODELS_DIR) with onnxruntime, preprocessing images and
tokenizing prompts as the estimator's pipeline does, so each prompt's scores
match the first segmentation pass in the cluster. Each image is encoded once
and each prompt once, so many prompts can be compared in minutes.

For each image and prompt it prints the presence score, how many of SAM 3's
200 regions pass --threshold, and, when the image comes with the part's pixel
box, the score of the best region matching the part (box IoU of 0.5 or more)
and of the best other region, and the part's rank.

onnxruntime is not among the solution's Python dependencies; install it into
a directory of its own and put that on PYTHONPATH (research/tools/README.md):

  PYTHONPATH=$HOME/.local/share/omts-onnxruntime \\
    bazel run //research/tools:prompt_sweep -- \\
    --image /tmp/benchy.png:560,330,690,440 --prompt object --prompt "toy boat"
"""

import argparse
import importlib.util
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

RESOLUTION = 1008
REGION_IOU = 0.5


def _load_tokenizer_module():
  """The pipeline's SAM 3 tokenizer, loaded by path: importing it as a package
  module runs the package's __init__, which needs TensorRT and OpenCV."""
  rel = Path("foundationpose_perception_pipeline/inference/sam3/tokenizer.py")
  for root in sys.path:
    path = Path(root) / rel
    if path.exists():
      spec = importlib.util.spec_from_file_location("sam3_tokenizer", path)
      module = importlib.util.module_from_spec(spec)
      spec.loader.exec_module(module)
      return module
  raise ImportError(f"{rel} not found on sys.path")


def _sigmoid(x: np.ndarray) -> np.ndarray:
  return 1.0 / (1.0 + np.exp(-np.clip(x, -80.0, 80.0)))


def _iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
  """IoU of boxes a (N, 4) with box b (4,), all x0, y0, x1, y1."""
  lo = np.maximum(a[:, :2], b[:2])
  hi = np.minimum(a[:, 2:], b[2:])
  inter = np.prod(np.clip(hi - lo, 0, None), axis=1)
  area = lambda r: (r[..., 2] - r[..., 0]) * (r[..., 3] - r[..., 1])  # noqa: E731
  return inter / (area(a) + area(b) - inter)


class Sam3Onnx:
  """SAM 3's vision encoder, text encoder and mask decoder on onnxruntime."""

  def __init__(self, models_dir: Path):
    import onnxruntime as ort  # Not a solution dependency; see the docstring.

    def load(name):
      return ort.InferenceSession(
        str(models_dir / f"{name}.onnx"), providers=["CPUExecutionProvider"]
      )

    self.vision = load("sam3_vision_encoder")
    self.text = load("sam3_text_encoder")
    self.decoder = load("sam3_mask_decoder")
    tokenizer = _load_tokenizer_module()
    self.context_length = tokenizer.DEFAULT_CONTEXT_LENGTH
    self.tokenizer = tokenizer.Sam3TextTokenizer(
      models_dir / "bpe_simple_vocab_16e6.txt.gz"
    )

  def encode_image(self, rgb: np.ndarray) -> dict[str, np.ndarray]:
    """The pipeline's set_image: bilinear resize, scale to [-1, 1], CHW."""
    resized = np.asarray(
      Image.fromarray(rgb).resize(
        (RESOLUTION, RESOLUTION), Image.Resampling.BILINEAR
      ),
      dtype=np.float32,
    )
    norm = (resized / 255.0 - 0.5) / 0.5
    image = np.ascontiguousarray(np.transpose(norm, (2, 0, 1))[None])
    names = [o.name for o in self.vision.get_outputs()]
    return dict(
      zip(names, self.vision.run(None, {"image": image}), strict=True)
    )

  def encode_text(self, prompt: str) -> dict[str, np.ndarray]:
    ids = self.tokenizer.tokenize([prompt], context_length=self.context_length)
    names = [o.name for o in self.text.get_outputs()]
    out = self.text.run(None, {"input_ids": np.asarray(ids, dtype=np.int64)})
    return dict(zip(names, out, strict=True))

  def regions(self, image_feats, text_feats, width: int, height: int):
    """Boxes (pixels, x0 y0 x1 y1), scores and presence for one prompt."""
    feed = {
      i.name: (image_feats | text_feats)[i.name]
      for i in self.decoder.get_inputs()
    }
    names = [o.name for o in self.decoder.get_outputs()]
    out = dict(zip(names, self.decoder.run(None, feed), strict=True))
    presence = float(_sigmoid(out["presence_logit"].reshape(-1)[0]))
    scores = _sigmoid(out["pred_logits"][0].reshape(-1)) * presence
    cx, cy, w, h = out["pred_boxes"][0].T
    boxes = np.stack(
      [
        (cx - w / 2) * width,
        (cy - h / 2) * height,
        (cx + w / 2) * width,
        (cy + h / 2) * height,
      ],
      axis=1,
    )
    return boxes, scores, presence


def _parse_image(arg: str) -> tuple[Path, np.ndarray | None]:
  path, _, box = arg.partition(":")
  return Path(path), (
    np.array([float(v) for v in box.split(",")]) if box else None
  )


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument(
    "--image",
    action="append",
    required=True,
    help="PNG path, optionally :x0,y0,x1,y1 with the part's pixel box",
  )
  parser.add_argument("--prompt", action="append", default=[])
  parser.add_argument(
    "--prompts_file", type=Path, help="more prompts, one per line"
  )
  parser.add_argument("--threshold", type=float, default=0.1)
  parser.add_argument(
    "--models_dir",
    type=Path,
    default=Path(
      os.environ.get(
        "NVIDIA_POSE_ESTIMATOR_MODELS_DIR",
        Path.home() / "intrinsic-models/nvidia_pose_estimator",
      )
    ),
  )
  args = parser.parse_args()
  prompts = list(args.prompt)
  if args.prompts_file:
    prompts += [
      line.strip()
      for line in args.prompts_file.read_text().splitlines()
      if line.strip() and not line.startswith("#")
    ]
  if not prompts:
    parser.error("give at least one --prompt or --prompts_file")

  t0 = time.time()
  sam3 = Sam3Onnx(args.models_dir)
  print(f"loaded SAM 3 in {time.time() - t0:.0f} s")
  texts = {p: sam3.encode_text(p) for p in prompts}
  for image_arg in args.image:
    path, part_box = _parse_image(image_arg)
    rgb = np.asarray(Image.open(path).convert("RGB"))
    t0 = time.time()
    feats = sam3.encode_image(rgb)
    print(f"\n{path.name} (encoded in {time.time() - t0:.0f} s)")
    print(
      f"  {'prompt':28s} presence  regions>{args.threshold:g}"
      + ("   part  rank  best other" if part_box is not None else "   best")
    )
    for prompt in prompts:
      boxes, scores, presence = sam3.regions(
        feats, texts[prompt], rgb.shape[1], rgb.shape[0]
      )
      line = f"  {prompt:28s} {presence:8.3f}  {int((scores > args.threshold).sum()):10d}"
      if part_box is None:
        line += f"   {scores.max():.3f}"
      else:
        is_part = _iou(boxes, part_box) >= REGION_IOU
        part = float(scores[is_part].max()) if is_part.any() else 0.0
        other = float(scores[~is_part].max()) if (~is_part).any() else 0.0
        rank = int((scores > part).sum()) + 1 if is_part.any() else 0
        line += f"   {part:.3f}  {rank:4d}  {other:.3f}"
      print(line, flush=True)


if __name__ == "__main__":
  main()
