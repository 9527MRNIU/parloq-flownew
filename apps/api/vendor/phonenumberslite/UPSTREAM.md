# phonenumberslite vendored dependency

- Package: `phonenumberslite`
- Version: `9.0.34`
- Upstream repository: <https://github.com/daviddrysdale/python-phonenumbers>
- Upstream tag and commit: `v9.0.34` / `671b53f52cc6e6d28eaeea71180137d2bdc315ac`
- Registry wheel: `phonenumberslite-9.0.34-py2.py3-none-any.whl`
- Source archive: `phonenumberslite-9.0.34.tar.gz`
- License: Apache-2.0 (see `9.0.34/LICENSE`)

The checked-in wheel is the API runtime dependency. The extracted `9.0.34`
directory and source archive are retained as an auditable source snapshot.
Local synchronization and Docker builds install the wheel from this directory,
so they do not require the upstream repository or package registry to remain
available.

To update the dependency, review the upstream release and license, replace the
wheel, source archive and extracted snapshot, update the checksums and metadata
in this directory, refresh `uv.lock`, then run the API tests and API image build.
