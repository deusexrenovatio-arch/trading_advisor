import argparse

from moex_carry.config import load_settings
from moex_carry.ui.app import run_ui


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    args = parser.parse_args()
    settings = load_settings(args.config)
    run_ui(settings)


if __name__ == "__main__":
    main()
