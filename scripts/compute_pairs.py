import argparse

from moex_carry.config import load_settings
from moex_carry.pipeline import compute_pairs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    args = parser.parse_args()
    settings = load_settings(args.config)
    compute_pairs(settings)


if __name__ == "__main__":
    main()
