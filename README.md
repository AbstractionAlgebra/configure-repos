# configure-repos

Version **1.1** - released **2026-09-09**.

Ubuntu APT repository configuration with the `setup_apt_repos` role.

Ansible role and fleet playbook for Ubuntu 22.04 (jammy) and 24.04 (noble), amd64. Uses existing HTTPS mirrors under `/ubuntu22/` and `/ubuntu24/`, legacy `.list` output, upstream signatures, corporate signing keys, and a supplied internal CA bundle. ESM Infra, ESM Apps, corporate and configured FIPS channels are included; Docker CE is off by default. No Ubuntu Pro attachment, package installation, package upgrade, FIPS activation, or reboot is performed.

## Version 1.1 migration

The role is now `setup_apt_repos`, all configuration variables and registered results use `apt_repos_`, and the inventory group is `apt_workstations`. Update custom inventories and role references before running this release; previous variable names are not aliases. Project versions use `major.minor` format.

Managed output is now `apt-repos-managed.list` with `99zz-apt-repos-security`. The role removes the predecessor security file after validating its replacement; normal source cleanup removes the previous managed list. Repository selection, trust requirements, and failure reporting are unchanged.

## Prepare

Use a Linux Ansible controller with Python 3 and ansible-core 2.18 or 2.19. Targets need Python 3, APT, gpgv, coreutils (`timeout`), SSH access, and privilege escalation already available. The role does not bootstrap packages. HTTPS transport is implemented; NFS mounting is outside this implementation because the agreed deployment uses HTTPS.

1. Edit `inventory/hosts.yml` with real workstations and SSH settings.
2. Change `apt_repos_mirror_origin` in `inventory/group_vars/apt_workstations.yml`. The supplied `repo.corp.example` is a reserved placeholder. Do not add a trailing slash.
3. Put approved public-key and CA files into `assets/jammy/` and `assets/noble/`, following `assets/README.md`. No fake keys or certificates are included.
4. Enter their approved SHA-256 values in the inventory variables. Missing files or placeholder hashes fail preflight before changes to workstation APT files.
5. Verify mirrored FIPS channels/suites, components and pockets. Defaults are examples of upstream layout, not a claim that every channel exists for every release. Remove unmirrored channels from `apt_repos_fips_channels`; override definitions where necessary.

From this directory:

```sh
umask 077
ansible-playbook site.yml --syntax-check
ansible-playbook site.yml --check --diff
ansible-playbook site.yml --limit 'workstation22.example,localhost' --ask-become-pass
ansible-playbook site.yml --ask-become-pass
```

Include `localhost` in `--limit` so the final controller report play runs. Omit `--ask-become-pass` when your approved escalation method does not need it. Check mode validates prerequisites and previews files, but cannot validate metadata or simulate newly copied trust files. Use a maintenance window: replacement is atomic per file, not a transaction across all APT files. Coordinate with any other APT/source-management tooling.

## Repository layout

For 22.04, the base is `https://repo.corp.example/ubuntu22`; for 24.04 it is `https://repo.corp.example/ubuntu24`.

| Repository | Path beneath base | Suites (`REL` = jammy or noble) | Components |
| --- | --- | --- | --- |
| Ubuntu | ubuntu | REL, REL-updates, REL-security, REL-backports | main restricted universe multiverse |
| ESM Infra | infra/ubuntu | REL-infra-security, REL-infra-updates | main |
| ESM Apps | apps/ubuntu | REL-apps-security, REL-apps-updates | main |
| FIPS | fips/ubuntu | REL-updates (verify mirror) | main |
| FIPS Updates | fips-updates/ubuntu | REL-updates (verify mirror) | main |
| Corporate | corp/ubuntu | REL | main |
| Docker (optional) | docker/linux/ubuntu | REL | stable |

Override `apt_repos_repositories` for different mirror layouts; each entry has `name`, `path`, `suites`, `components`, and `key`. The FIPS channel list and optional Docker entry are appended to it. Set `apt_repos_docker_enabled: true` in host/group inventory as needed. Filenames are shared between OS releases; approved asset contents/checksums can differ by release.

The role deploys `/etc/apt/sources.list.d/apt-repos-managed.list` and removes `/etc/apt/sources.list` plus every other `.list` or `.sources` entry in `/etc/apt/sources.list.d`, including Ubuntu's default Deb822 files, Pro-generated files, and old Docker entries. This is intentional and has no automatic rollback. Inactive files with other suffixes are not active APT repositories and are left alone. Nonstandard configured APT source directories fail preflight. Another tool could recreate sources later; this role is not a continuous enforcement service.

## Trust and validation

Public keys are copied to `/etc/apt/keyrings` and selected explicitly by `signed-by` in each source. The controller compares supplied files against inventory SHA-256 pins; an administrator must establish the approved signing fingerprints and provenance before recording those pins. File hashes verify approved bytes, not independent ownership of the signing key. Metadata signature verification is performed by APT/gpgv.

The internal CA bundle is copied to `/etc/apt/keyrings/corp-ca-bundle.pem` and explicitly selected by APT's HTTPS `CaInfo` setting. **This establishes trust for APT only**, without changing the system-wide trust store or requiring installation of `ca-certificates`. Supply approved PEM CA certificates and configure mirrors to serve their intermediate certificate chain. TLS peer and hostname verification remain enabled. Redirects are disabled. No runtime downloads of keys, certificates or packages occur.

`apt-get update` uses `APT::Update::Error-Mode=any`, a 30-second transport timeout, and a 600-second total deadline (configurable). Nonzero exit status and `W:`/`E:` diagnostics fail validation, including invalid signatures, expired metadata and failed downloads. There is no fallback to unsigned metadata or disabled expiry validation. A successful refresh may reuse unchanged cached indexes through normal HTTP conditional requests; errors cannot be silently accepted as a successful refresh. Existing package-manager hooks remain site-owned; review them if they initiate unrelated actions.

FIPS repository access does not make a machine FIPS-enabled or STIG-compliant. This role does not set FIPS/ESM package priorities, holds or package selection policy; those affect later package operations and belong in a separately reviewed patching policy. Both FIPS channels are modeled because they were requested; select the channels approved for your environment before rollout.

## Failures and reports

Failures are rescued per workstation, recorded in `ansible.log`, and included in `reports/last-run.json`. Source files are left as they stand, including any partially completed configuration. Connection losses inside the role are converted into local assertion failures so a failed serial batch does not stop later batches. Initial unreachable hosts are also recorded. The playbook continues other workstations.

The default batch size is 10; override `apt_repos_batch_size`. The JSON statuses are `success`, `failed`, `incomplete`, or `check_mode`. Rescued failures can produce an exit code of zero: automation consuming this playbook must inspect the report, not only the process exit status. The report is the latest invocation, while `ansible.log` preserves task diagnostics across invocations. Archive both under your organization's log-retention policy. Concurrent invocations should use separate project copies to avoid sharing report/log paths.

## Validation

```sh
python3 -m pip install -r tests/requirements.txt
python3 -m unittest discover -s tests -v
```

Unit checks parse all YAML, render both releases with Docker on/off, verify trust and repository boundaries, exercise rejected inputs, and parse fleet reports. The included GitHub Actions workflow also syntax-checks with Ansible and runs an HTTPS signed-fixture integration test on disposable Ubuntu 22.04/24.04 containers. See `tests/README.md` for details and execution limitations.

## References

- [Canonical ESM source suites and keyring names](https://documentation.ubuntu.com/security/security-updates/esm/)
- [Canonical FIPS keyring definition](https://github.com/canonical/ubuntu-pro-client/blob/main/uaclient/entitlements/fips.py)
- [Docker Ubuntu repository and docker.asc](https://docs.docker.com/engine/install/ubuntu/)
- [Ubuntu archive keyring files](https://packages.ubuntu.com/noble/all/ubuntu-keyring/filelist)
- [APT strict update errors](https://manpages.ubuntu.com/manpages/jammy/man8/apt-get.8.html)
- [Ansible error handling](https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_error_handling.html)
