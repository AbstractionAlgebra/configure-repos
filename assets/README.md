# Offline trust assets

Create `jammy/` and `noble/` subdirectories here. Each needs:

| Filename | Approved source |
| --- | --- |
| ubuntu-archive-keyring.gpg | Ubuntu ubuntu-keyring package |
| ubuntu-pro-esm-infra.gpg | Canonical Ubuntu Pro client distribution |
| ubuntu-pro-esm-apps.gpg | Canonical Ubuntu Pro client distribution |
| ubuntu-pro-fips.gpg | Canonical Ubuntu Pro client distribution; shared by FIPS channels |
| corp-archive-keyring.gpg | Your internal repository signing authority |
| corp-ca-bundle.pem | Your internal PKI; PEM CA certificates, no private keys |
| docker.asc | Docker's armored Ubuntu repository signing key; only needed when enabled |

Obtain these on your approved connected staging system, verify their provenance and full signing fingerprints through your approved process, then transfer them offline to the controller. Modern Canonical names use `ubuntu-pro-*`; older packages may have `ubuntu-advantage-*` filenames. If importing an older artifact, verify its signing identity and explicitly map/rename it to the configured asset name. Do not assume a renamed file contains the correct key.

Use binary exported public keyrings for `.gpg` and ASCII-armored public keys for `.asc`, not GnuPG keybox databases. For review on the staging system:

```sh
gpg --show-keys --with-fingerprint --with-subkey-fingerprint ubuntu-pro-fips.gpg
sha256sum *.gpg *.asc *.pem
```

Record reviewed SHA-256 pins under the matching release in inventory. Do not derive and approve hashes blindly from files of unknown provenance. The role never invokes `pro attach` and never installs Pro packages on clients to obtain these files.
