# libsignal-node vendored dependency

- Package: `libsignal`
- Version: `6.0.0`
- Upstream repository: <https://github.com/WhiskeySockets/libsignal-node>
- Upstream commit: `bcea72df9ec34d9d9140ab30619cf479c7c144c7`
- Commit archive: `libsignal-6.0.0.tgz`
- License: GPL-3.0 (see `6.0.0/LICENSE`)

Baileys 6.7.24 normally installs this package directly from GitHub. The
checked-in archive was packed from the exact locked commit and is installed
through the root npm dependency and override. The extracted `6.0.0` directory
is retained as an auditable runtime source snapshot. Gateway builds therefore
do not need the upstream Git repository to remain available.

To update this dependency, use the commit required by the reviewed Baileys
release, replace the archive and extracted snapshot, update the checksum and
metadata, refresh `package-lock.json`, then run the gateway tests, build and
image build.
