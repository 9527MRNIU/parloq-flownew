White-label account linking capability starter.

Keep the component tags in index.html. Change layout, CSS variables, ::part()
styles, background assets and customer copy as needed. Do not add protocol IDs,
gateway URLs, access tokens, direct pairing requests or phone persistence.

Functional component copy can be overridden with locale keys prefixed by
accountLink., for example accountLink.submit and accountLink.waiting.
The built-in phone-linking instructions cover 15 base locales and follow the
official WhatsApp Help Center navigation terms for Android and iPhone.
Keep account-link-locale-switcher to provide a native-name locale picker. It
reloads the current page with the selected lang value and locks after pairing.
