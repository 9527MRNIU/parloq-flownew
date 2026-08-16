# WhatsApp Web phone-linking copy sources

The phone-number linking instructions in `account-link-elements/v1` are
captured directly from the localized runtime resources served by
`https://web.whatsapp.com/`. The current snapshot was collected on 2026-08-16.
The WhatsApp Help Center is not the primary copy source.

## Collection contract

For each supported locale, request `https://web.whatsapp.com/` with the locale's
`Accept-Language` value, follow the localized `static.whatsapp.net` JavaScript
resources referenced by that HTML, and extract only these runtime modules:

- `WAWebLinkDevicePhoneNumberCodeScreen.react`: page title and code state copy.
- `WAWebLinkDeviceCommonInstructions.react`: the four phone-linking steps and
  their embedded navigation labels.
- `WAWebWaSquareIconIcon.react`: WhatsApp square icon path.
- `WAWebMenuIcon.react`: Android overflow-menu icon path.
- `WAWebSettingsIphoneIcon.react`: iPhone Settings icon path.

The component preserves the runtime message patterns and inserts the localized
navigation labels and SVG icons at the same placeholders used by WhatsApp Web.
It does not copy the WhatsApp Web page layout, download promotion, QR flow,
security claims, account limits, or other unrelated interface copy.

| Component locale | Request `Accept-Language` | WhatsApp runtime locale |
| --- | --- | --- |
| `en` | `en-US` | `en_US` |
| `zh-CN` | `zh-CN` | `zh_CN` |
| `hi` | `hi-IN` | `hi_IN` |
| `id` | `id-ID` | `id_ID` |
| `pt-BR` | `pt-BR` | `pt_BR` |
| `es` | `es-ES` | `es_ES` |
| `ru` | `ru-RU` | `ru_RU` |
| `ur` | `ur-PK` | `ur_PK` |
| `de` | `de-DE` | `de_DE` |
| `tr` | `tr-TR` | `tr_TR` |
| `ar` | `ar-SA` | `ar_AR` |
| `fa` | `fa-IR` | `fa_IR` |
| `bn` | `bn-BD` | `bn_IN` |
| `it` | `it-IT` | `it_IT` |
| `fr` | `fr-FR` | `fr_FR` |

Country-specific browser locales continue to fall back to these base packs.
For example, `es-MX`, `es-CO`, `es-ES`, and `es-AR` use `es`; `en-US`,
`en-GB`, `en-IN`, `en-NG`, and `en-ZA` use `en` unless a theme supplies a
regional override.

Because WhatsApp can deploy new localized resource hashes at any time, future
copy refreshes must repeat this collection process against the live page and
review the resulting module strings before updating the bundled snapshot.
