// Account + notebook domain seed — the canonical Source-of-Truth for the web
// app's demo identity and notebook taxonomy.
//
// The values are now CODEGEN'd from the single demo SoT (ops/demo/demo_identity
// .json + demo_dataset.json) by ops/demo/build_demo.py into ./account.generated.
// This module re-exports them so existing imports (`from './account.seed'`) and
// the transformers stay unchanged. Edit the SoT JSON + regenerate; never edit
// the .generated.ts by hand. This file holds DOMAIN values only — no
// API-response shaping (that lives in ../transformers).

export {
  SEED_NOW_ISO,
  NOTEBOOK_DEFAULT_COLOR,
  NOTEBOOK_SEEDS,
  ACCOUNT_SEED,
} from './account.generated'
export type { NotebookSeed, AccountSeed } from './account.generated'
