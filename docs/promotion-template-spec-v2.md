# Promotion template specification v2

Status: current for new templates (`promotion-template/v2`). Existing v1
templates remain supported.

Machine-readable schema:
[`schemas/promotion-template-v2.schema.json`](schemas/promotion-template-v2.schema.json).

## Boundary

Templates own presentation, localization and pairing-state UI only. The
platform owns channel resolution, logical protocol routing, account-group
assignment, public API authentication, Meta Browser Pixel/CAPI delivery and
interaction policy. A template must never store a protocol node ID, construct
gateway URLs, persist phone numbers or inject an analytics SDK.

The same template can be attached to channels that route to different logical
protocol nodes or explicit fallback pools. A channel route change affects only
new pairing attempts; the template contract does not change.

## Manifest

```json
{
  "schema": "promotion-template/v2",
  "version": "2.0.0",
  "entry": "index.html",
  "format": "static-bundle",
  "capabilities": ["phone-pairing"],
  "runtime": "promotion-browser-bridge/v2",
  "requirements": {
    "pairingContract": "promotion-public-pairing/v1",
    "componentKit": "account-link-elements/v1"
  },
  "interactionProtection": "platform",
  "defaultLocale": "en",
  "supportedLocales": ["en", "zh-CN"],
  "i18n": {
    "mode": "bundled",
    "path": "locales/{locale}.json",
    "fallbackLocale": "en"
  }
}
```

The ZIP and localization constraints are unchanged from v1: one `index.html`,
self-contained relative assets, no source maps or external scripts, ZIP at most
20 MB, expanded content at most 50 MB, at most 500 files and at most 5 MB per
file.

## Runtime bridge

The platform injects `promotion-runtime-config` and
`window.PromotionBridge`. Templates may use only these bridge methods:

```ts
interface PromotionBridgeV2 {
  version: 'promotion-browser-bridge/v2'
  submitPhone(
    phone: string,
    metadata?: Record<string, string | number | boolean | null>
  ): Promise<Response>
  getPairingStatus(pairing: PairingHandle): Promise<Response>
  cancelPairing(pairing: PairingHandle): Promise<Response>
}
```

`submitPhone` returns `data.pairing`, including `pairingCode`, `attemptId`,
`expiresAt` and an opaque pairing handle. The whole object must be passed back
to `getPairingStatus` or `cancelPairing`; v2 templates must not construct an
Authorization header or put any token in a URL.

Only `pairingStatus === "verified" && verified === true` is success.
`code_issued` and `waiting_phone` continue polling; `reconnecting` displays a
recovering state; `failed`, `expired` and `cancelled` stop polling and enable a
new attempt. `accountState` is diagnostic and must never be interpreted as
pairing success.

## White-label account-link elements

New visual themes should require `account-link-elements/v1` and compose the
platform-owned elements below instead of copying pairing logic into the ZIP:

```html
<account-link-flow>
  <account-link-locale-switcher></account-link-locale-switcher>
  <phone-number-field></phone-number-field>
  <account-link-submit></account-link-submit>
  <pairing-code-panel></pairing-code-panel>
  <app-launch-actions></app-launch-actions>
  <account-link-status></account-link-status>
  <account-initialization-status></account-initialization-status>
</account-link-flow>
```

The phone element derives its initial country from browser localization, uses
bundled phone metadata and always permits an explicit user override. Channel
country is not a phone-prefix source. The app launcher attempts WhatsApp or
WhatsApp Business only after a user click and always preserves manual
instructions as fallback. Themes customize CSS variables and exposed
`::part()` names; they do not replace component network behavior.

`account-link-locale-switcher` lists the manifest's `supportedLocales` by
native language name and reloads the same page with the selected `lang` query
value. It is intended both for end-user preference and rapid template QA. The
selector locks after a pairing code is issued so a live attempt is not
abandoned by an accidental language change.

The built-in functional copy covers `en`, `zh-CN`, `hi`, `id`, `pt-BR`, `es`,
`ru`, `ur`, `de`, `tr`, `ar`, `fa`, `bn`, `it`, and `fr`. The code title, four
manual phone-linking steps, localized navigation labels, and three guide icons
are captured from the localized runtime resources served by
`web.whatsapp.com`. The collection contract is recorded in
`docs/whatsapp-phone-linking-copy-sources.md`. Themes can style the icons'
exposed `::part()` names but should not remove them from the manual fallback.

The runtime may reject a new start with `account_already_linked`,
`number_unavailable`, `pairing_in_progress` or `rate_limited`. Templates must
not infer tenant or account details from these categories.

After verified pairing, `initializationStatus` can be `pending`, `syncing`,
`ready`, `failed` or `unsupported`. Initialization failure never changes a
verified pairing into a failed pairing.

## Channel-provided behavior

- Meta standard-event mapping is channel configuration. The runtime generates
  one event ID and uses it for Browser Pixel and CAPI deduplication.
- `inAppBrowserMode="guide_external"` means the template should show a neutral
  instruction to open the system browser when the runtime detects a supported
  in-app browser. It is guidance, not a promise that JavaScript can force an
  external browser.
- New-account marketing eligibility is snapshotted when the account is first
  created. Templates must not expose or alter it.
- Visible phone values contain digits only and never a leading plus sign.

## Acceptance checklist

- Preview completes submit, code, waiting and verified states without creating
  an account.
- A real test channel covers waiting, reconnecting, verified, failed, expired,
  cancelled and retry UI.
- All status/cancel calls go through the v2 bridge.
- No protocol ID, gateway URL, access token, phone persistence, third-party SDK
  or product-control-plane brand leaks into the public bundle.
- Locales are complete, RTL is correct, and 360×800, 390×844, 768×1024 and
  1440×900 render without overflow.
