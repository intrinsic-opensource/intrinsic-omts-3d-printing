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

"""Runs the reBot's simulation-only printed-part pick-and-place demo."""

from collections.abc import Sequence

from absl import app, flags, logging
from intrinsic.solutions import deployments

from src.behaviors.rebot_pick_place import build_rebot_pick_place_tree
from src.core.config import RobotConfig
from src.core.infeed import GridInfeedStrategy
from src.core.tray import Tray
from src.core.types import SlotState
from src.core.workpiece import Workpiece
from src.hardware.robot import Robot

_ADDRESS = flags.DEFINE_string(
  "address",
  "localhost:17080",
  "gRPC address of the running reBot solution deployment.",
)
_NUM_CYCLES = flags.DEFINE_integer(
  "num_cycles",
  1,
  "Number of A-to-B-to-A cycles; values <= 0 repeat continuously.",
)


def main(argv: Sequence[str]) -> None:
  if len(argv) > 1:
    raise app.UsageError("Too many command-line arguments.")

  tray = Tray(
    name="rebot_infeed",
    rows=1,
    cols=1,
    pitch_x=0.0,
    pitch_y=0.0,
    origin_frame="root",
  )
  part_slot = tray.get_slot(0, 0)
  part_slot.workpiece = Workpiece(
    id="rebot_printed_part",
    cad_model_name="rebot_printed_part",
  )
  part_slot.state = SlotState.OCCUPIED
  infeed_strategy = GridInfeedStrategy(tray)

  solution = deployments.connect(address=_ADDRESS.value)
  robot_config = RobotConfig(
    arm_part_name="rebot",
    tool_object_name="gripper",
    tool_frame_name="tool_frame",
  )
  robot = Robot(solution=solution, config=robot_config)
  tree = build_rebot_pick_place_tree(
    robot=robot,
    infeed_strategy=infeed_strategy,
    tool_object_name=robot_config.tool_object_name,
    num_cycles=_NUM_CYCLES.value,
  )
  logging.info(
    "Executing simulation-only reBot pick-and-place (cycles=%d)...",
    _NUM_CYCLES.value,
  )
  solution.executive.run(tree)


if __name__ == "__main__":
  app.run(main)
