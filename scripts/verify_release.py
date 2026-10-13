"""Inspect a copied release in an isolated path, without accessing the game."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(exe, arguments, env, cwd, expected=0):
    result=subprocess.run([str(exe),*arguments],env=env,cwd=cwd,capture_output=True,
                          text=True,encoding='utf-8',errors='replace',timeout=180)
    if result.returncode!=expected:
        raise RuntimeError(f'Command {arguments} failed ({result.returncode}): {result.stdout}\n{result.stderr}')
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('folder',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    folder=args.folder.resolve()
    manifest=json.loads((folder/'file-manifest.json').read_text(encoding='utf-8'))
    actual={p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}
    if actual != set(manifest)|{'file-manifest.json'}:
        raise RuntimeError('Unexpected or missing release files')
    for name,expected in manifest.items():
        file=(folder/name).resolve()
        if not file.is_relative_to(folder) or digest(file)!=expected:
            raise RuntimeError('Integrity mismatch: '+name)
    forbidden={'samples','runs','accounts','.git','.runtime','.venv-release','__pycache__'}
    if any(forbidden.intersection(Path(name).parts) for name in actual):
        raise RuntimeError('Private or development files included')
    if 'config.json' in actual:
        raise RuntimeError('User config included')
    with tempfile.TemporaryDirectory(prefix='DotAbyss 独立路径 ') as temp:
        base=Path(temp)
        copied=base/'中文 空格 程序'
        shutil.copytree(folder,copied)
        env=os.environ.copy()
        for key in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','DOTABYSS_DATA_DIR'):
            env.pop(key,None)
        env['PATH']=str(Path(env.get('SystemRoot','C:/Windows'))/'System32')
        env['LOCALAPPDATA']=str(base/'用户数据')
        exe=copied/'DotAbyss.exe'
        result=run(exe,['self-test','--gui-check','--report',str(base/'smoke.json')],env,base)
        smoke=json.loads((base/'smoke.json').read_text(encoding='utf-8'))
        if not smoke.get('frozen') or not smoke.get('passed'):
            raise RuntimeError('Frozen smoke report invalid')
        # Reset is an offline path/config test; no window discovery occurs.
        run(exe,['reset-config'],env,base)
        config=base/'用户数据/DotAbyss/config.json'
        if not config.exists():
            raise RuntimeError('Config not written to LocalAppData')
        content=config.read_bytes()
        run(exe,['reset-config'],env,base)
        backups=list(config.parent.glob('config.backup-*.json'))
        if len(backups)!=1 or backups[0].read_bytes()!=content:
            raise RuntimeError('Config backup failed')
        config.write_text('{broken-json',encoding='utf-8')
        # Analyze fails on invalid config before accessing any image or desktop.
        run(exe,['analyze','--image',str(base/'absent.png'),'--config',str(config)],env,base,expected=1)
        if not list((config.parent/'runs').glob('error-*.log')):
            raise RuntimeError('Error log missing')
        template=copied/'assets/templates/manifest.json'
        template.rename(template.with_suffix('.missing'))
        run(exe,['self-test'],env,base,expected=1)
        report={'passed':True,'files_checked':len(manifest),'frozen_self_test':smoke,
                'isolated_cwd':True,'chinese_space_path':True,'python_env_removed':True,
                'path_only_system32':True,'localappdata_config_and_backup':True,
                'invalid_config_error_log':True,'missing_manifest_rejected':True,
                'independent_machine_test':False,'game_test':False}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
