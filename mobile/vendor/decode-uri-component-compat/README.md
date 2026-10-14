# URL decoder compatibility

Expo Router 57 uses query-string 7, which calls its decoder as a CommonJS
function. The security-fixed decode-uri-component 0.5.0 exports an ESM default.
This package only adapts that export; the decoder stays in the integrity-locked
upstream npm package, installed under the `decode-uri-component-modern` alias.

The root dependency and query-string override ensure npm hoists the local package
correctly. Keep both until Expo Router supplies a compatible patched decoder.
Node 22.22.3 and Expo Metro/Hermes exports are verified. Run
`node scripts/test-query-decoding.mjs` from `mobile` after dependency changes.

Advisory: https://github.com/advisories/GHSA-vcc3-ghjq-m6fr
