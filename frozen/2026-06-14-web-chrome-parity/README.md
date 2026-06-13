# Frozen Web / Chrome / Parity Surface

This directory freezes the former Vite web pilot, Chrome extension, and web/chrome parity tooling.

Rules:
- Active build, test, CI, docs registry, and generators must not depend on files under this directory.
- Do not edit frozen code in place for product work.
- To revive any surface, move the relevant subtree back into the active tree and reintroduce explicit build/test/docs ownership.
