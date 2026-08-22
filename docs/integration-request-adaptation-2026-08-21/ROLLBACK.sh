#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="${1:-$(git -C "$script_dir" rev-parse --show-toplevel)}"
patch_file="$script_dir/system-rollback.patch"

if [[ ! -d "$repo_root" ]]; then
  printf 'ROLLBACK_RESULT=invalid_target target=%s\n' "$repo_root" >&2
  exit 2
fi

if git -C "$repo_root" apply --reverse --check "$patch_file"; then
  git -C "$repo_root" apply --reverse "$patch_file"
  restored_status="system_patch_reversed"
elif git -C "$repo_root" apply --check "$patch_file"; then
  restored_status="system_already_restored"
else
  printf 'ROLLBACK_RESULT=target_does_not_match_patch target=%s\n' "$repo_root" >&2
  exit 3
fi

adapted_dir="$repo_root/tmp/integration-request-adapted-2026-08-22"
rm -f -- \
  "$adapted_dir/ds_net.js" \
  "$adapted_dir/ds_net_native.js" \
  "$adapted_dir/ds_net.test.js" \
  "$adapted_dir/ds_net_native.test.js"
rmdir -- "$adapted_dir" 2>/dev/null || true
importable_dir="$repo_root/tmp/integration-request-importable-2026-08-22"
rm -f -- \
  "$importable_dir/ds_net.js" \
  "$importable_dir/ds_net_native.js" \
  "$importable_dir/bootstrap.js" \
  "$importable_dir/index.html" \
  "$importable_dir/integration.json"
rmdir -- "$importable_dir" 2>/dev/null || true
rm -f -- \
  "$repo_root/tmp/integration-request-importable-2026-08-22.test.js" \
  "$repo_root/tmp/integration-request-adapted-full-js-2026-08-22.zip"
rm -f -- "$repo_root/docs/integration-request-adaptation-2026-08-21/integration-request-adapted-2026-08-22.zip"

printf 'ROLLBACK_RESULT=%s target=%s adapted_status=absent importable_status=absent package_status=absent\n' \
  "$restored_status" "$repo_root"
