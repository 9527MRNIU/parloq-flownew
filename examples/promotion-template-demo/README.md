# Standard promotion template

This directory is the production reference implementation for
[`promotion-template/v2`](../../docs/promotion-template-spec-v2.md). New
templates should start from this bundle and change only presentation, copy and
assets unless the v2 contract explicitly allows more.

After changing files, rebuild the importable archive from this directory:

```bash
zip -qrFS ../promotion-template-demo.zip . -x README.md
```

The template must use `window.PromotionBridge.submitPhone`,
`getPairingStatus` and `cancelPairing`. It must not construct public API URLs,
authorization headers, account requests or gateway requests itself. Preview
uses the same bridge with simulated pairing data; a channel render resolves the
channel's configured logical protocol route.
Visible phone numbers contain digits only and never render a leading `+`;
the platform normalizes the protocol value at the API boundary.

Visible copy uses `data-copy` (and the supported `data-copy-*` attribute markers).
The platform localizes the initial HTML response before first paint and includes
the same map as `localizedCopy` for later form and pairing interactions.
