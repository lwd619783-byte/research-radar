// Vercel builds only the allowlisted static output, never repository evidence.
const fs = require('node:fs');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const m = JSON.parse(fs.readFileSync('release.json', 'utf8'));
assert.equal(m.schemaVersion, 2);
assert.match(m.sourceSHA, /^[0-9a-f]{40}$/);
assert.match(m.runId, /^[0-9]+$/);
assert.deepEqual(m.blockers, []);
assert.deepEqual(fs.readdirSync('public').sort(), ['index.html', 'robots.txt', 'version.json']);
assert.deepEqual(Object.keys(m.files).sort(), ['index.html', 'robots.txt', 'version.json']);
for (const [name, expected] of Object.entries(m.files)) {
  assert(fs.lstatSync(`public/${name}`).isFile());
  assert.equal(crypto.createHash('sha256').update(fs.readFileSync(`public/${name}`)).digest('hex'), expected);
}
assert.equal(crypto.createHash('sha256').update(fs.readFileSync('history.json')).digest('hex'), m.historySHA256);
const version = JSON.parse(fs.readFileSync('public/version.json', 'utf8'));
assert.equal(version.sourceSHA, m.sourceSHA);
assert.equal(version.dataSHA256, m.dataSHA256);
// The immutable source files above are checked before this build-only derivative.
// It lets the authenticated browser identify the exact currently served Git build.
if (!process.argv.includes('--check-only')) {
  assert.equal(process.env.VERCEL_ENV, 'production');
  assert.equal(process.env.VERCEL_GIT_COMMIT_REF, 'production');
  assert.match(process.env.VERCEL_GIT_COMMIT_SHA || '', /^[0-9a-f]{40}$/);
  fs.writeFileSync('public/version.json', JSON.stringify({...version, productionSHA: process.env.VERCEL_GIT_COMMIT_SHA}));
}
console.log(JSON.stringify({verified: true, sourceSHA: m.sourceSHA, runId: m.runId, priceDateRange: m.priceDateRange}));
