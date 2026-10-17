#!/usr/bin/env python3
"""Read-only project discovery/preflight. This is not a Paperclip plugin or scheduler."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys

IGNORED_PARTS = {'.git', 'node_modules', '.venv', 'venv', '.next', '.local', 'dist', 'build', '__pycache__'}
RULE_NAMES = {'AGENTS.md', 'AGENT.md', 'Agent.md', 'agents.md'}
ROLE_PARENTS = {'docs/project/agent-roles', '.agents/roles', '.codex/agents'}
EXTRA_RULES = {'docs/project/single-developer-workflow.md', 'docs/project/agent-os-convergence-policy.md'}
ROLE_NAMES = ['product-manager', 'product', 'builder', 'reviewer', 'acceptance']


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular_inside(root, relative):
    p = root / relative
    # Reject symlink components before reading. Do not follow rules outside the checkout.
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('rule_path_is_symlink: ' + relative)
    if not p.is_file() or not p.resolve().is_relative_to(root):
        raise ValueError('rule_file_unavailable: ' + relative)
    return p


def discover(repo):
    root = Path(repo).expanduser().resolve(strict=True)
    root = Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve()
    revision = git(root, 'rev-parse', 'HEAD').decode().strip()
    names = git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0')
    names = sorted(set(n for n in names if n and not any(x in IGNORED_PARTS for x in Path(n).parts)))
    candidates = [n for n in names if Path(n).name in RULE_NAMES or n in EXTRA_RULES or n == '.paperclip/roles.json'
                  or (str(Path(n).parent) in ROLE_PARENTS and Path(n).suffix in {'.md', '.toml'})]
    rules, warnings, inline_hints = [], [], []
    for name in candidates:
        try:
            data = regular_inside(root, name).read_bytes()
        except ValueError as exc:
            warnings.append(str(exc))
            continue
        try:
            committed = git(root, 'show', revision + ':' + name)
            matches = digest(committed) == digest(data)
        except subprocess.CalledProcessError:
            matches = False
        rules.append({'path': name, 'sha256': digest(data), 'matches_revision': matches})
        if Path(name).name in RULE_NAMES:
            for heading in re.findall(r'^#{1,6}\s+(?:[0-9.]+\s+)?((?:Product Manager|Product(?: / Product Owner)?|Builder|Reviewer|Acceptance)(?: Agent)?)\s*$', data.decode('utf8', errors='replace'), re.MULTILINE | re.IGNORECASE):
                inline_hints.append({'path': name, 'heading': heading})
        if not matches:
            warnings.append('uncommitted_rule_requires_explicit_baseline_resolution: ' + name)
    from roles import resolve, fingerprints, RoleError
    try:
        registry = resolve(root)
    except RoleError as exc:
        warnings.append('role_resolution_error: ' + str(exc))
        registry = {'roles': {}, 'project_roles': []}
    roles = {}
    for role in ROLE_NAMES:
        matches = [r['path'] for r in rules if Path(r['path']).stem == role]
        if len(matches) == 1:
            roles[role] = matches[0]
        elif len(matches) > 1:
            warnings.append('ambiguous_role: ' + role)
    workflow = 'docs/project/single-developer-workflow.md'
    tier = 'full' if len(roles) == len(ROLE_NAMES) and any(r['path'] == workflow for r in rules) else 'partial' if registry['project_roles'] or roles or inline_hints else 'lite'
    checks = {}
    package = root / 'package.json'
    if package.exists() and not package.is_symlink():
        try:
            scripts = json.loads(package.read_text()).get('scripts', {})
            checks = {k: {'command': ['npm', 'run', k], 'review_required': True} for k in ['test', 'lint', 'typecheck', 'build'] if k in scripts}
        except (ValueError, OSError):
            warnings.append('package_json_unreadable_or_invalid')
    if inline_hints:
        warnings.append('inline_roles_require_explicit_mapping_and_review')
    if not rules:
        warnings.append('no_recognized_rule_files_found')
    warnings.append('discovery_is_not_authority_or_runtime_isolation')
    return {
        'schema_version': 1,
        'kind': 'project-adapter-draft',
        'activation': 'observe_only',
        'project_id': root.name,
        'repository_root': str(root),
        'repository_revision': revision,
        'git_common_dir': git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir').decode().strip(),
        'profile_tier': tier,
        'rules': rules,
        'detected_roles': roles,
        'role_registry': fingerprints(registry),
        'project_roles': registry['project_roles'],
        'inline_role_hints': inline_hints,
        'suggested_checks': checks,
        'policy_proposal': {'allow_pr_creation': False, 'allow_merge': False, 'allow_deploy': False,
                            'allow_production': False, 'max_building_per_repository': 1},
        'missing_runtime_enforcement': ['approved_packet_schema', 'repository_lease', 'sha_bound_review',
                                        'fresh_role_context', 'sandbox_and_secret_boundary', 'quota_pause',
                                        'pr_publication_broker', 'bounded_retries_and_cleanup'],
        'warnings': warnings,
    }


def check(path):
    value = json.loads(Path(path).read_text())
    if value.get('schema_version') != 1 or value.get('kind') != 'project-adapter-draft':
        raise ValueError('unsupported_profile_schema')
    if value.get('activation') != 'observe_only':
        raise ValueError('this_tool_cannot_enable_execution')
    root = Path(value['repository_root']).resolve(strict=True)
    if git(root, 'rev-parse', 'HEAD').decode().strip() != value['repository_revision']:
        raise ValueError('repository_revision_changed; regenerate_and_review_profile')
    for rule in value['rules']:
        if Path(rule['path']).is_absolute() or '..' in Path(rule['path']).parts:
            raise ValueError('invalid_rule_path')
        if digest(regular_inside(root, rule['path']).read_bytes()) != rule['sha256']:
            raise ValueError('rule_bytes_changed: ' + rule['path'])
    if any(not r.get('matches_revision') for r in value['rules']):
        raise ValueError('uncommitted_rules_require_baseline_resolution')
    if any(w.startswith('role_resolution_error:') for w in value.get('warnings',[])):
        raise ValueError('role_resolution_error; resolve_mapping_first')
    if value.get('role_registry'):
        from roles import resolve, fingerprints
        if fingerprints(resolve(root)) != value['role_registry']:
            raise ValueError('role_registry_changed; regenerate_profile')
    print(json.dumps({'profile_consistent': True, 'activation': 'observe_only',
                      'execution_authorized': False, 'warning_count': len(value.get('warnings', []))}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    scan = sub.add_parser('inspect')
    scan.add_argument('repo')
    scan.add_argument('--output', required=True)
    verify = sub.add_parser('check')
    verify.add_argument('profile')
    args = parser.parse_args()
    if args.action == 'inspect':
        profile = discover(args.repo)
        # Exclusive create protects a manually reviewed profile from accidental replacement.
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(profile, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({'profile_written': str(Path(args.output).resolve()),
                          'tier': profile['profile_tier'], 'rules': len(profile['rules']),
                          'activation': 'observe_only'}))
    else:
        check(args.profile)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print('profile_error: ' + str(exc), file=sys.stderr)
        sys.exit(1)
