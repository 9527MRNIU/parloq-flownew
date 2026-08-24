# Baileys vendored dependency

- Package: `@whiskeysockets/baileys`
- Version: `6.7.24`
- Upstream repository: <https://github.com/WhiskeySockets/Baileys>
- Upstream commit: `e0629940ee2d335b0c0119367fd2a934e0fa3189`
- Registry archive: `whiskeysockets-baileys-6.7.24.tgz`
- License: MIT (see `6.7.24/LICENSE`)

The checked-in registry archive is the gateway dependency used by
`package.json`. The extracted `6.7.24` directory is retained as an auditable
runtime source snapshot. The package's Git-hosted `libsignal` dependency is
redirected to the separately vendored archive through the root npm override.

To update this dependency, review the upstream release and license, replace
the archive and extracted snapshot, review and vendor its matching `libsignal`
revision, update checksums and metadata, refresh `package-lock.json`, then run
the gateway tests, build and image build.
