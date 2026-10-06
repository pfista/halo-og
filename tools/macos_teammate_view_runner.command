#!/bin/zsh
# Double-click in Finder to open the isolated teammate-view runner in Terminal.
set -e
runner_tools_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
cd -- "${runner_tools_dir}/.."
exec /usr/bin/env python3 "${runner_tools_dir}/macos_teammate_view_runner.py" "$@"
