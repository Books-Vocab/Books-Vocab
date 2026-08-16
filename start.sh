#!/usr/bin/env bash
set -euo pipefail

# Keep the repository-root launcher aligned with the product's active local
# service. UITest visual inspection is run-scoped and has no repository-root
# launcher; use the iOS Catalog or evidence helper for that purpose.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/lab/podcast/start.sh" "$@"
