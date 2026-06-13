// Re-export shim — backend pydantic TS mirrors now live in the @kg/types
// workspace package (packages/types/src/index.ts). This shim keeps all existing
// `from './types'` / `from '../api/types'` imports across web working unchanged.
// SoT = backend/src/kg/api_models/*.py; edit @kg/types, not this file.
export * from '@kg/types'
