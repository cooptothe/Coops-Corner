"""No-spend VPS reboot evidence and isolated web-artifact recovery smoke.

Never reboots, starts a collector, changes service settings, or restores live data.
The operator's shell batch performs the separately authorized reboot.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time

ROOT=Path('/srv/corner/app')
EVIDENCE=ROOT/'retained/release-evidence'
BEFORE=EVIDENCE/'reboot-before.json'
AFTER=EVIDENCE/'reboot-after.json'
REQUIRED=('corner-staging-accounts.service','corner-staging-api.service',
          'corner-staging-web.service','caddy.service','postgresql.service',
          'corner-backup.timer','corner-readiness.timer')


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=15).strip()


def write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(value,stream,indent=2);stream.write('\n')
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def phase():
    if not BEFORE.exists():return 'prepare'
    previous=json.loads(BEFORE.read_text(encoding='utf-8'))
    if boot_id()==previous['boot_id']:return 'reboot'
    return 'verify'


def reject_collectors(listing):
    checked=[]
    for line in listing.splitlines():
        fields=line.split()
        if not fields:continue
        name=fields[0]
        if name.startswith('corner') and 'collect' in name and name.endswith(('.service','.timer')):
            # is-enabled returns nonzero for disabled/static units, so inspect
            # the unit-file listing and query activity independently.
            if len(fields)<2 or fields[1] not in ('disabled','masked','static'):
                raise RuntimeError('Collector could start automatically; no-spend reboot refused')
            active=subprocess.run(['systemctl','is-active','--quiet',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
            if active.returncode==0:raise RuntimeError('Collector is active; no-spend reboot refused')
            checked.append(name)
    return checked


def state():
    if Path.cwd().resolve()!=ROOT:
        raise RuntimeError('Run from /srv/corner/app')
    from dotenv import dotenv_values,load_dotenv
    staging=Path('/srv/corner/config/staging.env')
    worker=Path('/srv/corner/config/collection.env')
    stage=dotenv_values(staging);collection=dotenv_values(worker)
    if (stage.get('CORNER_PRIVATE_BETA')!='1' or stage.get('CORNER_REFRESH_DAILY_CAP')!='0'
            or stage.get('ODDS_API_KEY') or collection.get('CORNER_COLLECTION_ENABLED')!='0'):
        raise RuntimeError('Disabled collection/private-beta configuration check failed')
    load_dotenv(staging,override=True)
    from corner.billing_config import checkout_config
    if checkout_config() is not None:raise RuntimeError('Checkout is enabled')
    units={}
    for unit in REQUIRED:
        if command('systemctl','is-enabled',unit)!='enabled' or command('systemctl','is-active',unit)!='active':
            raise RuntimeError('Required unit is not enabled and active: '+unit)
        units[unit]='enabled/active'
    checked=reject_collectors(command('systemctl','list-unit-files','--type=service,timer','--no-legend','--no-pager'))
    dependencies=command('systemctl','list-dependencies','--all','--plain','--no-legend','multi-user.target')
    if any('corner' in line and 'collect' in line for line in dependencies.splitlines()):
        raise RuntimeError('Collector appears in the boot dependency graph')
    command('pg_isready','-h','127.0.0.1','-p','5432')
    found=set()
    for line in command('ss','-H','-lnt').splitlines():
        address=line.split()[3];host,_,port=address.rpartition(':')
        if port in ('3000','8765','8766','5432'):
            if host not in ('127.0.0.1','[::1]','::1'):
                raise RuntimeError('Internal service exposed outside loopback')
            found.add(port)
    if found!={'3000','8765','8766','5432'}:raise RuntimeError('Internal listener missing')
    fingerprints={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (staging,worker)}
    billing=os.environ.get('CORNER_BILLING_CONFIG')
    if billing:
        path=Path(billing)
        if not path.is_file():raise RuntimeError('Configured billing file is missing')
        fingerprints[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    secret=ROOT/'retained/auth_secret'
    if secret.is_file():fingerprints[str(secret)]=hashlib.sha256(secret.read_bytes()).hexdigest()
    return dict(boot_id=boot_id(),release_commit=command('git','rev-parse','HEAD'),
                units=units,collector_units_checked=checked,private_fingerprints=fingerprints,
                checked_at_utc=datetime.now(timezone.utc).isoformat())


def verify(before, after):
    if before['boot_id']==after['boot_id']:raise RuntimeError('Boot identity did not change')
    if before['release_commit']!=after['release_commit']:raise RuntimeError('Release changed across reboot; review before acceptance')
    if before['private_fingerprints']!=after['private_fingerprints']:
        raise RuntimeError('Private configuration/session material changed across reboot; inspect privately')
    return dict(result='passed',release_commit=after['release_commit'],boot_changed=True,
                required_units_enabled_active=True,private_configuration_unchanged=True,
                collector_disabled=True,checkout_disabled=True,provider_calls=0,
                checked_at_utc=after['checked_at_utc'],
                scope='Host reboot and disabled-config continuity; not a live-odds, payment, or full database rollback test')


def artifact():
    """Serve an isolated copy of the active compiled artifact; no live files replaced."""
    if Path.cwd().resolve()!=ROOT:raise RuntimeError('Run from /srv/corner/app')
    web=ROOT/'web';build=web/'.next'
    ident=(build/'BUILD_ID').read_text().strip()
    if not (build/'required-server-files.json').is_file():raise RuntimeError('Production artifact is incomplete')
    from pipelines.release_probe import fetch
    # Cache is disposable and can dwarf the actual deployable artifact.
    size=sum(p.stat().st_size for p in build.rglob('*') if p.is_file() and 'cache' not in p.relative_to(build).parts)
    if shutil.disk_usage('/srv/corner/backups').free < size*3+256*1024*1024:
        raise RuntimeError('Insufficient free space for isolated artifact rehearsal')
    with tempfile.TemporaryDirectory(prefix='web-recovery-probe-',dir='/srv/corner/backups') as folder:
        target=Path(folder)/'web';target.mkdir()
        shutil.copytree(build,target/'.next',ignore=lambda folder,names:['cache'] if Path(folder)==build and 'cache' in names else [])
        for name in ('package.json','next.config.ts'):
            shutil.copy2(web/name,target/name)
        shutil.copytree(web/'public',target/'public')
        (target/'node_modules').symlink_to(web/'node_modules',target_is_directory=True)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        environment={key:value for key,value in os.environ.items() if key in ('PATH','HOME','USER','LANG','TMPDIR')}
        environment.update(NODE_ENV='production',NEXT_TELEMETRY_DISABLED='1')
        EVIDENCE.mkdir(parents=True,exist_ok=True)
        log=EVIDENCE/'web-artifact-recovery-server.log'
        log_fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        os.chmod(log,0o600)
        with os.fdopen(log_fd,'wb') as stream:
            process=subprocess.Popen(['node',str(web/'node_modules/next/dist/bin/next'),'start',str(target),
                '--hostname','127.0.0.1','--port',str(port)],cwd=target,env=environment,stdout=stream,stderr=stream)
            try:
                origin=f'http://127.0.0.1:{port}'
                deadline=time.monotonic()+45
                while time.monotonic()<deadline and process.poll() is None:
                    if fetch(origin,'/login',timeout=2)['status']==200:break
                    time.sleep(.3)
                else:raise RuntimeError('Isolated saved-build startup failed; live app unchanged')
                checks={path:fetch(origin,path)['status'] for path in ('/login','/lab','/manifest.webmanifest',
                    '/assets/corner-icon-192.png','/api/refresh/v1/auth/me','/api/v1/health')}
                if list(checks.values())!=[200,200,200,200,401,401]:
                    raise RuntimeError('Saved-build routes/auth guards failed; live app unchanged')
                if (build/'BUILD_ID').read_text().strip()!=ident or (target/'.next/BUILD_ID').read_text().strip()!=ident:
                    raise RuntimeError('Artifact identity changed during rehearsal')
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=5)
    result=dict(result='passed',build_id=ident,isolated_saved_build_routes=checks,
        live_files_replaced=False,provider_calls=0,
        scope='Restored copy of current web build with installed dependencies; not a prior-release backend/schema rollback',
        checked_at_utc=datetime.now(timezone.utc).isoformat())
    write_private(EVIDENCE/'web-artifact-recovery.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('phase','prepare','verify','artifact'))
    args=parser.parse_args()
    try:
        if args.action=='phase':print(phase());return 0
        if args.action=='artifact':result=artifact()
        elif args.action=='prepare':
            if BEFORE.exists():raise RuntimeError('Reboot baseline already exists; verify it rather than overwriting evidence')
            result=state();write_private(BEFORE,result)
            result=dict(result='ready_for_authorized_reboot',release_commit=result['release_commit'],
                        collector_disabled=True,checkout_disabled=True,provider_calls=0)
        else:
            before=json.loads(BEFORE.read_text(encoding='utf-8'))
            result=verify(before,state());write_private(AFTER,result)
        print(json.dumps(result,indent=2));return 0
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        # Never include secret file contents or captured subprocess logs.
        print(json.dumps(dict(result='failed',error_type=type(error).__name__,action=args.action,
            reason=str(error) if isinstance(error,RuntimeError) else 'Private configuration, artifact, or system command check failed',
            guidance='Inspect recovery evidence and unit state; no configuration or live data was restored.')))
        return 1


if __name__=='__main__':raise SystemExit(main())
