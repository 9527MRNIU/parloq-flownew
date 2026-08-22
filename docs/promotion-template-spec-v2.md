# Promotion template specification v2

Status: historical and unsupported by the current importer
(`promotion-template/v2`). Use
[`promotion-template/v3`](promotion-template-spec-v3.md).

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

New v2 templates must declare
`requirements.componentKit="account-link-elements/v1"` and compose the
platform-owned account-link elements. Custom layout, CSS, branding and truthful
customer content remain template responsibilities; phone parsing, country
selection, CTA validity and pairing state are platform responsibilities.

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

New visual themes must require `account-link-elements/v1` and compose the
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

`account-link-submit` remains disabled until `phone-number-field` contains a
valid number and disables itself again while a request is pending. Templates
must not add a second primary CTA or bypass this validity gate with a custom
submit handler.

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

## Conversion and content baseline

- The first screen has one clear primary CTA. Phone input, country selection
  and the CTA have touch targets of at least 44×44 CSS px.
- Loading, invalid input, submitting, code issued, waiting, reconnecting,
  verified, expired, failed, cancelled and retry states must all remain usable.
- Claims about user counts, identity verification, encryption, privacy,
  delivery results or platform endorsement require real supporting data. If
  the product cannot supply that data, the claim must not be shown.
- Templates must support 360×800, 390×844, 768×1024 and 1440×900 without
  horizontal overflow, inaccessible controls or clipped status messages.
- Templates must not set `user-scalable=no` or otherwise lock zoom. The platform
  template policy owns viewport behavior.

## Resource and performance budget

- JavaScript gzip target: at most 250 KB across the bundle.
- CSS gzip target: at most 80 KB across the bundle.
- Prefer WebP/AVIF for large raster images. Images should declare `width`,
  `height` and `alt`; images after the primary visual should use lazy loading.
- Fonts are bundled under the template assets and use `font-display: swap`.
  Runtime CDN fonts, external images, external scripts and template-owned
  iframes are not allowed.
- The platform does not rewrite or optimize uploaded HTML and assets. Template
  authors remain responsible for applying the reported recommendations.

## Import quality report

Every newly imported or replaced ZIP receives a lightweight static quality
report. It records estimated JS/CSS gzip size, expanded size and image size,
then groups actionable warnings for source-map references, external resources,
template-owned iframes, large images, missing image metadata/lazy loading,
viewport problems, legacy schema use and missing platform components.

Unsafe paths, unsupported files, oversized packages and invalid manifests
remain hard import errors. Performance and markup findings are recommendations:
they are visible in template management but do not block use of an otherwise
valid template. Historical versions imported before this check display
"unchecked" until their ZIP is replaced.

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
- The primary CTA is disabled for an invalid number and while submission is in
  progress; country selection remains manually overridable.
- All status/cancel calls go through the v2 bridge.
- No protocol ID, gateway URL, access token, phone persistence, third-party SDK
  or product-control-plane brand leaks into the public bundle.
- Locales are complete, RTL is correct, and 360×800, 390×844, 768×1024 and
  1440×900 render without overflow.
- Content claims are supportable and the import quality report has no
  unexplained warnings.
