"""Destructive fixture: disposable Ubuntu only; never run on a workstation."""
import functools
import gzip
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, **kwargs).stdout


def main():
    if os.environ.get('APT_REPOS_DISPOSABLE') != '1' or os.geteuid() != 0:
        raise SystemExit('Requires root and APT_REPOS_DISPOSABLE=1 in a disposable Ubuntu environment.')
    os_release = Path('/etc/os-release').read_text()
    version = re.search(r'^VERSION_ID="(.*?)"', os_release, re.M).group(1)
    if version not in ('22.04', '24.04'):
        raise SystemExit('Only Ubuntu 22.04/24.04 fixtures are supported.')
    codename, prefix = ('jammy', 'ubuntu22') if version == '22.04' else ('noble', 'ubuntu24')
    before_packages = run('dpkg-query', '-W', '-f=${Package}\t${Version}\n')
    with tempfile.TemporaryDirectory(prefix='apt-repos-fixture-') as temp:
        work = Path(temp)
        work.chmod(0o755)
        gnupg = work / 'gnupg'
        gnupg.mkdir(mode=0o700)
        gpg = ['gpg', '--homedir', str(gnupg), '--batch', '--pinentry-mode', 'loopback', '--passphrase', '']
        run(*gpg, '--quick-generate-key', 'Fixture Only <fixture@example.invalid>', 'rsa2048', 'sign', '1d')
        key = subprocess.check_output(gpg + ['--export'])
        armored = subprocess.check_output(gpg + ['--armor', '--export'])
        assets = work / 'assets' / codename
        assets.mkdir(parents=True)
        for name in ['ubuntu-archive-keyring.gpg', 'ubuntu-pro-esm-infra.gpg', 'ubuntu-pro-esm-apps.gpg', 'ubuntu-pro-fips.gpg', 'corp-archive-keyring.gpg']:
            (assets / name).write_bytes(key)
        (assets / 'docker.asc').write_bytes(armored)
        # Test CA and leaf certificate are separate to exercise chain verification.
        run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-subj', '/CN=Fixture CA', '-addext', 'basicConstraints=critical,CA:TRUE',
            '-keyout', str(work / 'ca.key'), '-out', str(assets / 'corp-ca-bundle.pem'))
        run('openssl', 'req', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=localhost',
            '-keyout', str(work / 'server.key'), '-out', str(work / 'server.csr'))
        (work / 'extensions').write_text('subjectAltName=DNS:localhost\nbasicConstraints=CA:FALSE\nextendedKeyUsage=serverAuth\n')
        run('openssl', 'x509', '-req', '-in', str(work / 'server.csr'), '-CA', str(assets / 'corp-ca-bundle.pem'),
            '-CAkey', str(work / 'ca.key'), '-CAcreateserial', '-days', '1',
            '-extfile', str(work / 'extensions'), '-out', str(work / 'server.pem'))
        mirror = work / 'mirror'
        definitions = [
            ('ubuntu', [codename + s for s in ['', '-updates', '-security', '-backports']], ['main', 'restricted', 'universe', 'multiverse']),
            ('infra/ubuntu', [codename + '-infra-security', codename + '-infra-updates'], ['main']),
            ('apps/ubuntu', [codename + '-apps-security', codename + '-apps-updates'], ['main']),
            ('fips/ubuntu', [codename + '-updates'], ['main']),
            ('fips-updates/ubuntu', [codename + '-updates'], ['main']),
            ('corp/ubuntu', [codename], ['main']),
            ('docker/linux/ubuntu', [codename], ['stable']),
        ]
        for path, suites, components in definitions:
            for suite in suites:
                dist = mirror / prefix / path / 'dists' / suite
                entries = []
                for component in components:
                    folder = dist / component / 'binary-amd64'
                    folder.mkdir(parents=True)
                    for filename, content in [('Packages', b''), ('Packages.gz', gzip.compress(b''))]:
                        package_file = folder / filename
                        package_file.write_bytes(content)
                        entries.append(f' {hashlib.sha256(content).hexdigest()} {len(content)} {package_file.relative_to(dist).as_posix()}')
                now = datetime.now(timezone.utc)
                release = dist / 'Release'
                release.write_text(f'Origin: Fixture\nLabel: Fixture\nSuite: {suite}\nCodename: {suite}\nDate: {format_datetime(now)}\nValid-Until: {format_datetime(now + timedelta(hours=12))}\nArchitectures: amd64\nComponents: {" ".join(components)}\nSHA256:\n' + '\n'.join(entries) + '\n')
                run(*gpg, '--yes', '--digest-algo', 'SHA256', '--clearsign', '--output', str(dist / 'InRelease'), str(release))
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(mirror))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(work / 'server.pem', work / 'server.key')
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = f'https://localhost:{server.server_port}'
        inventory = work / 'inventory.json'
        variables = work / 'variables.json'
        variables.write_text(json.dumps({
            'apt_repos_asset_dir': str(work / 'assets'),
            'apt_repos_asset_sha256': {codename: {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in assets.iterdir() if f.is_file()}},
            'apt_repos_docker_enabled': True,
            'apt_repos_batch_size': 1,
            'apt_repos_timeout': 2,
            'apt_repos_refresh_deadline': 30,
        }))

        def play(hosts):
            inventory.write_text(json.dumps({'all': {'children': {'apt_workstations': {'hosts': {
                name: {'ansible_connection': 'local', 'ansible_python_interpreter': '/usr/bin/python3', 'apt_repos_mirror_origin': url}
                for name, url in hosts.items()}}}}}))
            result = run('ansible-playbook', 'site.yml', '-i', str(inventory), '-e', '@' + str(variables), cwd=ROOT)
            report = json.loads((ROOT / 'reports/last-run.json').read_text())
            print(result)
            return report, result

        sources = Path('/etc/apt/sources.list.d')
        sources.mkdir(exist_ok=True)
        (sources / 'obsolete.list').write_text('deb https://unreachable.example.invalid/ubuntu jammy main\n')
        (sources / 'obsolete.sources').write_text('Types: deb\nURIs: https://unreachable.example.invalid/ubuntu\nSuites: jammy\nComponents: main\n')
        try:
            report, _ = play({'good': origin})
            assert report['good']['status'] == 'success', report
            assert not (sources / 'obsolete.list').exists()
            assert not (sources / 'obsolete.sources').exists()
            assert not Path('/etc/apt/sources.list').exists()
            managed = sources / 'apt-repos-managed.list'
            original = managed.read_bytes()
            report, output = play({'good': origin})
            assert report['good']['status'] == 'success', report
            assert re.search(r'^good\s+:.*changed=0\s', output, re.M), output
            assert managed.read_bytes() == original
            key_path = assets / 'corp-archive-keyring.gpg'
            key_path.rename(assets / 'held-key')
            report, _ = play({'missing-key': origin})
            assert report['missing-key']['status'] == 'failed', report
            assert managed.read_bytes() == original
            (assets / 'held-key').rename(key_path)
            report, _ = play({'bad-first': 'https://localhost:9', 'good-second': origin})
            assert report['bad-first']['status'] == 'failed', report
            assert report['good-second']['status'] == 'success', report
            inrelease = mirror / prefix / 'corp/ubuntu/dists' / codename / 'InRelease'
            inrelease.write_text(inrelease.read_text().replace('Origin: Fixture', 'Origin: Tampered'))
            # Ensure APT re-fetches even if fixture timestamps share a second.
            os.utime(inrelease, (datetime.now().timestamp() + 5,) * 2)
            original = managed.read_bytes()
            report, _ = play({'tampered': origin})
            assert report['tampered']['status'] == 'failed', report
            assert managed.read_bytes() == original
            assert run('dpkg-query', '-W', '-f=${Package}\t${Version}\n') == before_packages
            print(f'PASS: signed HTTPS integration on Ubuntu {version}')
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
