#!/usr/bin/env python3
import logging
import sys

from .controller import FanController


def main():
    try:
        controller = FanController()
        controller.run()
    except Exception as e:
        logging.error(f"Failed to start fan controller: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

