"""Global shared-decks (Explore) domain package.

A *central* store at ``data_dir/shared_decks.db`` (outside ``users/<uid>/``)
holds curated/official decks browsable by guests. Owner is a column, never a
path — mirroring the ``translate_log`` cross-user precedent. See
``docs/plans/2026-07-09-shared-decks-library.md`` for the full data model.
"""
