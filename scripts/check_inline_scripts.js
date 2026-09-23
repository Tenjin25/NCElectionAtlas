#!/usr/bin/env node
const fs = require('node:fs');

const html = fs.readFileSync(process.argv[2] || 'index.html', 'utf8');
let checked = 0;
for (const match of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/gi)) {
  const attributes = match[1];
  const source = match[2];
  if (/\bsrc\s*=|type\s*=\s*["'](?:application\/json|module)/i.test(attributes) || !source.trim()) continue;
  try { new Function(source); }
  catch (error) {
    console.error(`Inline script ${checked + 1}: ${error.message}`);
    process.exit(1);
  }
  checked += 1;
}
console.log(`Parsed ${checked} inline scripts.`);
