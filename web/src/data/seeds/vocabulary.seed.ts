// Vocabulary domain seed — cards + graph links + review-event log.
//
// The values are now CODEGEN'd from the single demo SoT (ops/demo/demo_dataset
// .json) by ops/demo/build_demo.py into ./vocabulary.generated. This module
// re-exports them so existing imports (`from './vocabulary.seed'`) and the
// transformers stay unchanged. Edit the SoT JSON + regenerate; never edit the
// .generated.ts by hand. word←content, meaning←meaning, pos←strip-dot(pos),
// notebookId←slug(notebook NAME); graph links join by content within notebook.

export {
  CARD_DEFAULT_INTERVAL_HOURS,
  VOCAB_CARD_SEEDS,
  GRAPH_LINK_SEEDS,
  REVIEW_EVENT_LOG_SEED,
} from './vocabulary.generated'
export type {
  VocabCardSeed,
  GraphLinkSeed,
  ReviewEventLogSeed,
} from './vocabulary.generated'
