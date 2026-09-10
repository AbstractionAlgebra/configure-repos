# Validation

`test_project.py` runs portable YAML/template and configuration-boundary checks. It does not substitute for executing Ansible or validating APT signatures on Linux.

`integration.py` is destructive to APT source configuration and must run **only in a disposable Ubuntu 22.04/24.04 container or VM**. It requires `APT_REPOS_DISPOSABLE=1`, root, Python 3, ansible-playbook on PATH, openssl, gpg/gpgv, and APT. It creates a local HTTPS mirror with test-only keys and empty signed indexes, then tests:

- Offline trust deployment and replacement of legacy and Deb822 sources.
- Successful metadata refresh and unchanged installed package inventory.
- A second successful run with no configuration changes.
- Missing trust artifacts failing before source changes.
- A failed first serial host followed by a successful host.
- Rejection of tampered metadata, retaining source files for troubleshooting.

The fixture signing keys and CA are generated at runtime and are never deployment assets. Prerequisites are installed by CI setup before the role runs; the role itself installs no packages.

```sh
APT_REPOS_DISPOSABLE=1 python3 tests/integration.py
```

The GitHub Actions workflow runs the fixture on both OS versions and two Ansible minor versions. Real mirror URLs, production key fingerprints, FIPS publication details, and target STIG settings still need validation in your environment.
