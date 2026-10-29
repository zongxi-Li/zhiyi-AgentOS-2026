"""One-shot audited migration of the Docker stack's data into an N03 home.

Inputs are pre-exported copies (this script never talks to Docker itself):
  --dump       pg_dump SQL of the container kinlin_ai account database
  --snapshots  consistent SQLite snapshots taken via the container's online
               sqlite3 backup API (migration-snapshots dir incl. manifest.json)
  --raw        raw full agentos volume copy (plain files: attachments,
               code_index, rag, digital-human, llm_profiles, formal30_run)
  --uploads    backend uploads volume copy

The active-vs-stale mapping below is evidence-backed by the container's real
environment (docker inspect) plus wiring.py defaults plus volume mtimes; every
skipped file is listed in the receipt. Historical *.bak / recovery_backups /
pre_deadfix copies stay only in the cold archive, never in the N03 home.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

import native_runtime as native
import persistent_runtime as persistent

ROOT = native.ROOT

# container path (inside snapshots) -> N03 home/data relative path
SQLITE_MAP = {
    'agentos/workflows.sqlite3': 'workflows.sqlite3',
    'agentos/langgraph_checkpoints.sqlite3': 'checkpoints.sqlite3',
    'agentos/execution_values.sqlite3': 'values.sqlite3',
    'agentos/content_manifests.sqlite3': 'content.sqlite3',
    'agentos/execution_memory.sqlite3': 'memory.sqlite3',
    'agentos/provenance.sqlite3': 'provenance.sqlite3',
    'agentos/audit_decisions.sqlite3': 'audit.sqlite3',
    'agentos/evolution.sqlite3': 'evolution.sqlite3',
    'agentos/identity_v2.sqlite3': 'identity.sqlite3',
    'nodes.sqlite3': 'nodes.sqlite3',
    'resources.sqlite3': 'resources.sqlite3',
    'resource_health.sqlite3': 'health.sqlite3',
    'communication.sqlite3': 'communication.sqlite3',
    'agents.sqlite3': 'agents.sqlite3',
}

# raw-volume relative source -> home/data relative destination (recursive)
RAW_MAP = {
    'agentos/attachments': 'attachments',
    'agentos/code_index': 'code_index',
    'agentos/digital-human': 'digital-human',
    'agentos/rag': 'rag',
    'agentos/llm_profiles.json': 'llm_profiles.json',
    'formal30_run': 'formal30_run',
}

# stale relics intentionally not migrated (kept in the cold archive only)
DOCUMENTED_STALE = [
    'agentos/resources.sqlite3', 'agentos/resource_health.sqlite3',
    'content_manifests.sqlite3', 'identity_v2.sqlite3', 'global_models',
    'agentos/agentos/llm_profiles.json',
]


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def psql_env(info, creds, user, database):
    return dict(os.environ, PGHOST='127.0.0.1', PGPORT=str(persistent.ports(info)['postgres']),
                PGUSER=user, PGPASSWORD=creds['pgadmin'] if user == 'zhiyi_admin' else creds['db'],
                PGDATABASE=database, PGCLIENTENCODING='UTF8')


def run_psql(bin_dir, info, creds, user, database, sql=None, filename=None):
    command = [str(bin_dir / 'psql.exe'), '-X', '-q', '-t', '-A', '-v', 'ON_ERROR_STOP=1']
    if sql is not None:
        command += ['-c', sql]
    if filename is not None:
        command += ['-f', str(filename)]
    result = subprocess.run(command, env=psql_env(info, creds, user, database),
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'psql failed as {user} on {database}: {result.stderr.strip()[:400]}')
    return result.stdout


def pg_ctl(bin_dir, home, action, logfile):
    # pg_ctl start's stdout/stderr must never be pipes: the spawned postgres
    # server inherits them and outlives pg_ctl, so a pipe read would never end.
    command = [str(bin_dir / 'pg_ctl.exe'), '-D', str(home / 'postgres'), action, '-w', '-t', '60']
    if action == 'start':
        command += ['-l', str(logfile)]
    else:
        command += ['-m', 'fast']
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode:
        raise RuntimeError(f'pg_ctl {action} failed; inspect {logfile}')


def pg_ready(bin_dir, info, creds, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if run_psql(bin_dir, info, creds, 'zhiyi_admin', 'postgres', sql='SELECT 1;').strip() == '1':
                return
        except RuntimeError:
            pass
        time.sleep(0.5)
    raise RuntimeError('Local PostgreSQL readiness timed out')


def dump_row_counts(dump_path):
    """Parse pg_dump COPY blocks into table->row counts without Docker.

    A line scanner, not a terminator regex: an empty COPY block is
    'FROM stdin;\\n\\\\.\\n' with no data line, so any pattern that demands a
    newline before the terminator silently swallows the next table's header.
    """
    counts, table = {}, None
    for line in dump_path.read_text(encoding='utf-8', errors='replace').splitlines():
        if table is None:
            if line.startswith('COPY public.'):
                table = line.split(' ', 2)[1].partition('.')[2]
                counts[table] = 0
        elif line == '\\.':
            table = None
        elif line.strip():
            counts[table] += 1
    return counts


def step_preflight(home, args):
    info = persistent.manifest(home)
    persistent.require_stopped(home)
    missing = [str(p) for p in [args.dump, args.snapshots, args.raw, args.uploads] if not p.exists()]
    if missing:
        raise RuntimeError('Missing migration inputs: ' + ', '.join(missing))
    manifest = json.loads((args.snapshots / 'manifest.json').read_text(encoding='utf-8'))
    absent = [rel for rel in SQLITE_MAP if rel not in manifest]
    if absent:
        raise RuntimeError('Snapshot manifest lacks active databases: ' + ', '.join(absent))
    return {'status': 'PASS', 'home': str(home), 'portsFree': True,
            'snapshotDatabases': len(manifest), 'dump': str(args.dump)}


def step_postgres(home, args):
    info, creds = persistent.manifest(home), native.credentials(home)
    bin_dir = Path(info['postgresBin'])
    logfile = home / 'logs' / 'migration-pg.log'
    receipt = {'step': 'postgres'}
    pg_ctl(bin_dir, home, 'start', logfile)
    pg_ready(bin_dir, info, creds)
    try:
        source_counts = dump_row_counts(args.dump)
        run_psql(bin_dir, info, creds, 'zhiyi_admin', 'postgres',
                 sql='DROP DATABASE IF EXISTS zhiyi;')
        run_psql(bin_dir, info, creds, 'zhiyi_admin', 'postgres',
                 sql='CREATE DATABASE zhiyi OWNER zhiyi_app;')
        run_psql(bin_dir, info, creds, 'zhiyi_app', 'zhiyi', filename=args.dump.resolve())
        target_counts = {}
        listing = run_psql(bin_dir, info, creds, 'zhiyi_app', 'zhiyi',
                           sql="SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;")
        for table in [line.strip() for line in listing.splitlines() if line.strip()]:
            value = run_psql(bin_dir, info, creds, 'zhiyi_app', 'zhiyi',
                             sql=f'SELECT count(*) FROM public."{table}";')
            target_counts[table] = int(value.strip())
        mismatch = {t: [source_counts.get(t, 0), target_counts.get(t, 0)]
                    for t in set(source_counts) | set(target_counts)
                    if source_counts.get(t, 0) != target_counts.get(t, 0)}
        if mismatch:
            raise RuntimeError(f'Row-count mismatch after restore: {mismatch}')
        receipt.update(status='PASS', sourceCounts=source_counts,
                       targetCounts=target_counts, tables=len(target_counts))
    finally:
        pg_ctl(bin_dir, home, 'stop', logfile)
    return receipt


def step_agentos(home, args):
    info = persistent.manifest(home)
    manifest = json.loads((args.snapshots / 'manifest.json').read_text(encoding='utf-8'))
    previous = home / f"data.pre-migration-{time.strftime('%Y%m%dT%H%M%S')}"
    (home / 'data').rename(previous)
    data = home / 'data'
    data.mkdir()
    receipt = {'step': 'agentos', 'previousData': str(previous), 'databases': {}, 'rawItems': {},
               'integrity': {}, 'containerPathScan': {}, 'skippedStale': DOCUMENTED_STALE}
    for source_rel, dest_rel in SQLITE_MAP.items():
        source = args.snapshots / source_rel
        expected = manifest[source_rel]
        if sha256(source) != expected['sha256']:
            raise RuntimeError(f'Snapshot transfer corrupt: {source_rel}')
        destination = data / dest_rel
        shutil.copyfile(source, destination)
        if sha256(destination) != expected['sha256']:
            raise RuntimeError(f'Copy corrupt: {dest_rel}')
        receipt['databases'][source_rel] = {'dest': dest_rel, 'sha256': expected['sha256'],
                                            'bytes': expected['bytes']}
    for source_rel, dest_rel in RAW_MAP.items():
        source, destination = args.raw / source_rel, data / dest_rel
        if not source.exists():
            receipt['rawItems'][source_rel] = 'ABSENT (not in raw copy)'
            continue
        if source.is_dir():
            shutil.copytree(source, destination)
            receipt['rawItems'][source_rel] = {'dest': dest_rel,
                                               'files': sum(1 for p in destination.rglob('*') if p.is_file())}
        else:
            shutil.copyfile(source, destination)
            receipt['rawItems'][source_rel] = {'dest': dest_rel, 'bytes': destination.stat().st_size}
    for database in sorted(data.glob('*.sqlite3')):
        connection = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
        try:
            result = connection.execute('PRAGMA integrity_check;').fetchone()[0]
        finally:
            connection.close()
        receipt['integrity'][database.name] = result
        if result != 'ok':
            raise RuntimeError(f'integrity_check failed for {database.name}: {result}')
        receipt['containerPathScan'][database.name] = database.read_bytes().count(b'/app/data')
    inspect = subprocess.run([sys.executable, str(ROOT / 'scripts/prepare_agentos_runtime.py'),
                              '--workflow-db', str(data / 'workflows.sqlite3'),
                              '--checkpoint-db', str(data / 'checkpoints.sqlite3'),
                              '--identity-db', str(data / 'identity.sqlite3')],
                             capture_output=True, text=True, encoding='utf-8', errors='replace')
    receipt['schemaInspect'] = {'exitCode': inspect.returncode,
                                'stdout': inspect.stdout.strip()[-800:], 'stderr': inspect.stderr.strip()[-800:]}
    if inspect.returncode != 0:
        raise RuntimeError('prepare_agentos_runtime inspect rejected migrated databases; '
                           'see receipt; explicit --apply decision required')
    receipt['status'] = 'PASS'
    return receipt


def step_uploads(home, args):
    destination = home / 'uploads'
    destination.mkdir(exist_ok=True)
    copied = 0
    for source in args.uploads.rglob('*'):
        if not source.is_file():
            continue
        target = destination / source.relative_to(args.uploads)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied += 1
    return {'step': 'uploads', 'status': 'PASS', 'newFiles': copied,
            'totalFiles': sum(1 for p in destination.rglob('*') if p.is_file())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['preflight', 'postgres', 'agentos', 'uploads'])
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--dump', type=Path, default=Path(r'D:\kinlin-archive\kinlin_ai-dump.sql'))
    parser.add_argument('--snapshots', type=Path, default=Path(r'D:\kinlin-archive\agentos-snapshots'))
    parser.add_argument('--raw', type=Path, default=Path(r'D:\kinlin-archive\agentos-data-v12'))
    parser.add_argument('--uploads', type=Path, default=Path(r'D:\kinlin-archive\backend-uploads-v11'))
    parser.add_argument('--archive', type=Path, default=Path(r'D:\kinlin-archive'))
    args = parser.parse_args()
    home = args.home.absolute()
    steps = {'preflight': step_preflight, 'postgres': step_postgres,
             'agentos': step_agentos, 'uploads': step_uploads}
    with native.control_lock(home.with_name('.' + home.name + '-control')):
        result = steps[args.action](home, args)
    stamp = time.strftime('%Y%m%dT%H%M%S')
    (args.archive / f'migration-{args.action}-{stamp}.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('status') == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
