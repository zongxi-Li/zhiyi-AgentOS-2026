#!/bin/sh
set -eu
echo "This legacy configuration-only package is not a valid offline release." >&2
echo "Use: python3 -m ops.scripts.release.package_offline --help" >&2
exit 64
