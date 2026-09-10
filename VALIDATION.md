# Version 1.1 validation

Executed locally:

- All 8 unit checks passed, including the Ubuntu release/Docker rendering matrix, rejected inputs, explicit HTTPS trust, connection-loss guards, and JSON reporting.
- All 11 YAML files parsed and passed duplicate-key checks.
- Both Python test files compiled successfully.
- Role includes, inventory/report group names, and variable references were checked after renaming to `setup_apt_repos` / `apt_repos_`.

Not executed in this session:

- `ansible-playbook --syntax-check`: the local machine is Windows with no installed Linux/Ansible controller.
- The disposable Ubuntu HTTPS integration tests or the included CI workflow.
- Connections to actual workstations or internal repository mirrors.

The project includes a Linux CI workflow for Ansible 2.18/2.19 and Ubuntu 22.04/24.04. Run it (or equivalent disposable-environment tests) and a limited workstation rollout before broader deployment. Supply your approved keys, CA bundle, checksums and actual mirror origin first; no production trust material is included.
