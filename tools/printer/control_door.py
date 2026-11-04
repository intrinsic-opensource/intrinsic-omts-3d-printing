import argparse
import sys
from intrinsic.solutions import deployments


def parse_args():
  parser = argparse.ArgumentParser(description="Control printer door in OMTS world.")
  parser.add_argument(
      "--address", type=str, default="localhost:17080", help="Solution gRPC address."
  )
  parser.add_argument(
      "--action",
      choices=["open", "close", "set", "status"],
      default="open",
      help="Action to execute.",
  )
  parser.add_argument(
      "--angle",
      type=float,
      default=-1.57,
      help="Target angle in radians (e.g., -1.57 is ~90 deg open, 0.0 is closed).",
  )
  return parser.parse_args()


def main():
  args = parse_args()
  print(f"Connecting to Intrinsic solution at {args.address}...")
  solution = deployments.connect(address=args.address)
  world = solution.world

  printer = getattr(world, "printer", None)
  if printer is None:
    print(f"ERROR: 'printer' not found in active world. Available objects: {world.list_objects()}")
    sys.exit(1)

  joint_names = list(printer.joint_entity_names)
  current_positions = list(printer.joint_positions)
  print(f"Printer ID: {printer.id}")
  print(f"Registered joints: {joint_names}")
  print(f"Current positions: {current_positions}")

  if args.action == "status":
    return

  target_angle = 0.0 if args.action == "close" else args.angle

  # 1. Update the Belief World
  world.update_joint_positions(printer, [target_angle])
  print(f"[✓] Set Belief World joint position to {target_angle:.3f} rad.")

  # 2. Synchronize Gazebo sim_world
  if getattr(solution, "is_simulated", False) and solution.simulator is not None:
    print("[+] Syncing with Gazebo simulation (world.update_joint_positions(printer, [target_angle])...")
    world.update_joint_positions(printer, [target_angle])
    print("[✓] Gazebo simulation synchronized! Door is now visually positioned.")

  # 3. Confirm final state
  check_printer = getattr(solution.world, "printer", None)
  if check_printer:
    print(f"Confirmed joint position: {list(check_printer.joint_positions)}")


if __name__ == "__main__":
  main()