#!/usr/bin/env bash
set -euo pipefail

ssh -N \
  -L 11434:127.0.0.1:11434 \
  -i "${HOME}/.ssh/ndeamonrd.pem" \
  paperspace@184.105.157.30

