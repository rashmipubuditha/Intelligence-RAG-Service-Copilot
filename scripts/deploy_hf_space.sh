#!/usr/bin/env bash
# =============================================================================
# Publish the current commit to a Hugging Face Docker Space.
#
#   scripts/deploy_hf_space.sh <hf-username>/<space-name>
#
# A Space is a git repository that Hugging Face builds from its root Dockerfile.
# Rather than pushing this whole repository, the script pushes a snapshot of
# only what the image needs, with deploy/huggingface/README.md as the Space's
# README (it carries the YAML header Spaces require). That keeps the project
# README, the docs and binary files out of the Space.
#
# Each deploy force-pushes a single fresh commit: the Space is a build target,
# not a second source of truth.
#
# Authentication: git will prompt for your Hugging Face username and an access
# token with write scope (https://huggingface.co/settings/tokens).
# =============================================================================
set -euo pipefail

SPACE="${1:?usage: scripts/deploy_hf_space.sh <hf-username>/<space-name>}"
ROOT="$(git rev-parse --show-toplevel)"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD)"

if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
  echo "warning: uncommitted changes are NOT deployed; this publishes commit $COMMIT" >&2
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git -C "$ROOT" archive HEAD \
  Dockerfile .dockerignore requirements.txt main.py \
  backend eval/__init__.py eval/run.py eval/metrics.py eval/judges.py eval/datasets \
  policies frontend scripts/docker-entrypoint.sh \
  | tar -x -C "$WORK"
cp "$ROOT/deploy/huggingface/README.md" "$WORK/README.md"

cd "$WORK"
git init -q -b main
git add -A
git -c user.name="$(git -C "$ROOT" config user.name)" \
    -c user.email="$(git -C "$ROOT" config user.email)" \
    commit -q -m "Deploy $COMMIT"
git push --force "https://huggingface.co/spaces/$SPACE" main

echo "Deployed $COMMIT to https://huggingface.co/spaces/$SPACE"
