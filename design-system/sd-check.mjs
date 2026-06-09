import { execSync } from 'child_process';
import { readFileSync } from 'fs';

const SWIFT_PATH = 'ios/BooksAndVocab/Models/DesignTokens.swift';

let before;
try {
  before = readFileSync(SWIFT_PATH, 'utf8');
} catch {
  before = null;
}

execSync('npx style-dictionary build --config design-system/sd.config.mjs', { stdio: 'inherit' });

const after = readFileSync(SWIFT_PATH, 'utf8');
if (before !== after) {
  console.error('STALE: DesignTokens.swift is out of date. Run: npm run build');
  process.exit(1);
}
console.log('DesignTokens.swift is up to date.');
