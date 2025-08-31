#!/usr/bin/env python3
"""Compatibility wrapper for the new package layout.

This keeps direct execution of this file working by delegating to the
package entrypoint `k8_fan_controller`.
"""

from k8_fan_controller.__main__ import main

if __name__ == "__main__":
    main()

