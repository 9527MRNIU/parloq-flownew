# Promotion template demo

This directory is the reference implementation for
[`parloq-promotion-template/v1`](../../docs/promotion-template-spec-v1.md).

After changing files, rebuild the importable archive from this directory:

```bash
zip -qrFS ../promotion-template-demo.zip . -x README.md
```

The template must call `window.parloqSubmitPhone` and must not call account or
gateway APIs directly. Template preview uses the same bridge with simulated
pairing data; a channel render uses the real promotion and Baileys flow.
