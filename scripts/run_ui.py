import argparse
import sys

from moex_carry.config import load_settings
from moex_carry.server import run_server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    args = parser.parse_args()
    settings = load_settings(args.config)
    print("warning: scripts/run_ui.py is deprecated; use scripts/run_server.py", file=sys.stderr)
    run_server(settings)


if __name__ == "__main__":
    main()
