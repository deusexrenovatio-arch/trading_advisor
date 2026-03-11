import argparse

from moex_carry.config import load_settings
from moex_carry.server import run_server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    parser.add_argument("--host", type=str, default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    settings = load_settings(args.config)
    if args.host:
        settings.ui.host = args.host
    if args.port is not None:
        settings.ui.port = int(args.port)
    run_server(settings)


if __name__ == "__main__":
    main()
