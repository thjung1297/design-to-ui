#!/bin/bash
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
# plugin.json 과 marketplace.json 의 version 필드를 semver bump 합니다.
# 사용법: bash scripts/bump-version.sh <patch|minor|major>

set -euo pipefail

BUMP_TYPE="${1:?Usage: bump-version.sh <patch|minor|major>}"
PLUGIN_JSON="plugins/design-to-ui/.claude-plugin/plugin.json"
MARKETPLACE_JSON=".claude-plugin/marketplace.json"

if [ ! -f "$PLUGIN_JSON" ]; then
  echo "ERROR: $PLUGIN_JSON not found" >&2
  exit 1
fi

if [ ! -f "$MARKETPLACE_JSON" ]; then
  echo "ERROR: $MARKETPLACE_JSON not found" >&2
  exit 1
fi

CURRENT=$(jq -r '.version' "$PLUGIN_JSON")
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

case "$BUMP_TYPE" in
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  patch) PATCH=$((PATCH + 1)) ;;
  *) echo "ERROR: invalid bump type '$BUMP_TYPE' (patch|minor|major)" >&2; exit 1 ;;
esac

NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"

jq --arg v "$NEW_VERSION" '.version = $v' "$PLUGIN_JSON" > tmp.$$.json && mv tmp.$$.json "$PLUGIN_JSON"

# marketplace.json: metadata.version 과 design-to-ui plugin entry 의 version 도 함께 bump
jq --arg v "$NEW_VERSION" '
  .metadata.version = $v
  | (.plugins[] | select(.name == "design-to-ui") | .version) = $v
' "$MARKETPLACE_JSON" > tmp.$$.json && mv tmp.$$.json "$MARKETPLACE_JSON"

echo "$NEW_VERSION"
