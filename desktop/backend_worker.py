"""Dedicated, loopback-only service owned by the desktop application."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--managed", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Invalid port")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["SUBTITLE_STUDIO_DATA_DIR"] = str(args.data_dir.resolve())
    if args.env_file:
        os.environ["SUBTITLE_STUDIO_ENV_FILE"] = str(args.env_file.resolve())
    # Optional model caches belong in the user's data folder, not the application.
    os.environ.setdefault("HF_HOME", str(args.data_dir / "model-cache" / "huggingface"))
    os.environ.setdefault("MODELSCOPE_CACHE", str(args.data_dir / "model-cache"))
    logging.basicConfig(filename=args.data_dir / "backend.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    import uvicorn
    from backend.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_config=None,
                            loop="asyncio", http="h11", ws="websockets", access_log=False,
                            timeout_graceful_shutdown=4))
    if args.managed:
        def watch_parent() -> None:
            # EOF also stops the worker if its owning desktop process disappears.
            for line in sys.stdin:
                if line.strip() == "shutdown":
                    break
            server.should_exit = True
        threading.Thread(target=watch_parent, daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
