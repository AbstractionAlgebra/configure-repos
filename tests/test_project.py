import json
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'roles' / 'airgap_apt'


def environment():
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    env.filters['regex_replace'] = lambda s, pattern, replacement: re.sub(pattern, replacement, s)
    env.filters['urlsplit'] = lambda s, field: getattr(urlsplit(s), field)
    env.filters['to_json'] = json.dumps
    env.filters['to_nice_json'] = lambda v: json.dumps(v, indent=2)
    env.tests['match'] = lambda v, p: re.match(p, v) is not None
    return env


def resolve(value, context, env):
    if isinstance(value, str) and value.startswith('{{') and value.endswith('}}') and value.count('{{') == 1:
        return env.compile_expression(value[2:-2].strip())(**context)
    if isinstance(value, str):
        return env.from_string(value).render(**context)
    if isinstance(value, list):
        return [resolve(v, context, env) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, context, env) for k, v in value.items()}
    return value


def context(version, docker):
    env = environment()
    cfg = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
    cfg['airgap_apt_release'] = cfg['airgap_apt_release_map'][version]
    cfg['airgap_apt_docker_enabled'] = docker
    cfg['airgap_apt_corp_suite'] = resolve(cfg['airgap_apt_corp_suite'], cfg, env)
    # Evaluate the actual repository-building set_fact tasks.
    for task in yaml.safe_load((ROLE / 'tasks/preflight.yml').read_text()):
        if task['name'] not in ['Build base repository definitions', 'Add selected FIPS channels', 'Add optional Docker repository']:
            continue
        if task['name'] == 'Add optional Docker repository' and not docker:
            continue
        items = cfg['airgap_apt_fips_channels'] if 'loop' in task else [None]
        for item in items:
            cfg['item'] = item
            cfg['airgap_apt_repositories'] = resolve(cfg['airgap_apt_repositories'], cfg, env)
            cfg.update(resolve(task['ansible.builtin.set_fact'], cfg, env))
    return cfg


class ProjectTests(unittest.TestCase):
    def test_all_yaml_parses(self):
        files = list(ROOT.rglob('*.yml'))
        self.assertGreater(len(files), 8)
        for path in files:
            with self.subTest(path=path):
                self.assertIsNotNone(yaml.safe_load(path.read_text()))

    def test_release_docker_matrix(self):
        template = environment().from_string((ROLE / 'templates/repositories.list.j2').read_text())
        for version, codename, prefix, other in [('22.04', 'jammy', 'ubuntu22', 'noble'), ('24.04', 'noble', 'ubuntu24', 'jammy')]:
            for docker in [False, True]:
                with self.subTest(version=version, docker=docker):
                    rendered = template.render(**context(version, docker))
                    lines = [line for line in rendered.splitlines() if line.startswith('deb ')]
                    self.assertEqual(len(lines), 12 if docker else 11)
                    self.assertNotIn(other, rendered)
                    self.assertEqual('/docker/linux/ubuntu' in rendered, docker)
                    for line in lines:
                        self.assertIn(f'https://repo.corp.example/{prefix}/', line)
                        self.assertIn('arch=amd64', line)
                        self.assertIn('signed-by=/etc/apt/keyrings/', line)
                        self.assertNotIn('trusted=', line)
                        self.assertIn('check-valid-until=yes', line)
                    self.assertIn(f'{codename}-apps-security main', rendered)
                    self.assertIn(f'{codename}-infra-updates main', rendered)
                    self.assertNotIn('deb-src ', rendered)

    def test_https_trust_explicit(self):
        rendered = environment().from_string((ROLE / 'templates/security.conf.j2').read_text()).render(**context('24.04', False))
        self.assertIn('CaInfo "/etc/apt/keyrings/corp-ca-bundle.pem";', rendered)
        self.assertIn('repo.corp.example::Verify-Peer "true";', rendered)
        self.assertIn('repo.corp.example::Verify-Host "true";', rendered)
        self.assertIn('AllowRedirect "false";', rendered)

    def test_reject_untrusted_origin_shapes(self):
        task = next(t for t in yaml.safe_load((ROLE / 'tasks/preflight.yml').read_text()) if t['name'] == 'Validate mirror origin and release mapping')
        expr = environment().compile_expression(task['ansible.builtin.assert']['that'][0])
        for origin in ['http://repo.corp.example', 'https://user:password@repo.corp.example', 'https://repo.example/a', 'https://repo.example\nInjected', 'file:///mnt/mirror']:
            self.assertFalse(expr(airgap_apt_mirror_origin=origin), origin)
        self.assertTrue(expr(airgap_apt_mirror_origin='https://repo.example:8443'))

    def test_reject_source_injection_and_traversal(self):
        task = next(t for t in yaml.safe_load((ROLE / 'tasks/preflight.yml').read_text()) if t['name'] == 'Validate repository names and paths')
        checks = [environment().compile_expression(s) for s in task['ansible.builtin.assert']['that']]
        good = dict(name='corp', path='corp/ubuntu', key='corp-archive-keyring.gpg', suites=['jammy'], components=['main'])
        self.assertTrue(all(check(item=good) for check in checks))
        for field, value in [('path', '../etc'), ('key', '../../trusted.gpg'), ('suites', ['jammy\ndeb evil']), ('components', ['main [trusted=yes]'])]:
            bad = dict(good, **{field: value})
            self.assertFalse(all(check(item=bad) for check in checks), bad)

    def test_reports_include_failures_and_skip_unattempted(self):
        rendered = environment().from_string((ROOT / 'templates/report.json.j2').read_text()).render(
            groups={'airgap_workstations': ['good', 'bad', 'limited-out']},
            hostvars={'good': {'airgap_apt_result': {'status': 'success'}}, 'bad': {'airgap_apt_result': {'status': 'failed', 'message': 'TLS "error"\nsecond line'}}, 'limited-out': {}})
        result = json.loads(rendered)
        self.assertEqual(set(result), {'good', 'bad'})
        self.assertEqual(result['bad']['status'], 'failed')
        self.assertIn('\n', result['bad']['message'])

    def test_remote_operations_convert_unreachable_to_rescue(self):
        for file in ['preflight.yml', 'configure.yml', 'refresh.yml', 'security_check.yml']:
            tasks = yaml.safe_load((ROLE / 'tasks' / file).read_text())
            for i, task in enumerate(tasks):
                if any('ansible.builtin.' + action in task for action in ['command', 'stat', 'copy', 'template', 'file', 'find']):
                    self.assertTrue(task.get('ignore_unreachable'), task['name'])
                    self.assertIn('ansible.builtin.assert', tasks[i + 1])

    def test_no_install_upgrade_or_pro_actions(self):
        for path in (ROLE / 'tasks').glob('*.yml'):
            for task in yaml.safe_load(path.read_text()):
                self.assertNotIn('ansible.builtin.apt', task)
                self.assertNotIn('ansible.builtin.package', task)
                self.assertNotIn('ansible.builtin.shell', task)
        refresh = yaml.safe_load((ROLE / 'tasks/refresh.yml').read_text())[0]
        self.assertEqual(refresh['ansible.builtin.command']['argv'][-1], 'update')
        self.assertIn('APT::Update::Error-Mode=any', refresh['ansible.builtin.command']['argv'])


if __name__ == '__main__':
    unittest.main()
