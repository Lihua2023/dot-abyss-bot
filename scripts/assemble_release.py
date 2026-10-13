"""Allowlisted release assembly. No private samples, user configuration, or logs."""
from datetime import datetime, timezone
import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from version import VERSION


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git_revision():
    process = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
    return process.stdout.strip() if process.returncode == 0 else None


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def archive_folder(folder, target):
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(folder.rglob('*')):
            if file.is_file():
                archive.write(file, folder.name+'/'+file.relative_to(folder).as_posix())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--skip-replay',action='store_true')
    args=parser.parse_args()
    built = ROOT/'dist/DotAbyss'
    if not (built/'DotAbyss.exe').exists():
        raise RuntimeError('Build the EXE first')
    output = ROOT/'release-output'
    output.mkdir(exist_ok=True)
    # Never replace a prior release directory silently.
    release_dir = output/f'DotAbyss-{VERSION}-win-x64'
    release_dir.mkdir()
    for file in built.iterdir():
        if file.is_dir():
            shutil.copytree(file, release_dir/file.name)
        else:
            shutil.copyfile(file, release_dir/file.name)
    shutil.copytree(ROOT/'assets', release_dir/'assets')
    shutil.copytree(ROOT/'THIRD_PARTY_NOTICES', release_dir/'THIRD_PARTY_NOTICES')
    for name in ('config.default.json', 'LICENSE', 'CHANGELOG.md'):
        shutil.copyfile(ROOT/name, release_dir/name)
    shutil.copyfile(ROOT/'release/README-用户版.md', release_dir/'README-用户版.md')
    shutil.copyfile(ROOT/'release/使用前先阅读.txt', release_dir/'使用前先阅读.txt')
    shutil.copyfile(ROOT/'assets/guide/recommended-start.png', release_dir/'推荐起始界面.png')
    for filename, arguments in [('启动.cmd', ''), ('自检.cmd', 'self-test --gui-check')]:
        (release_dir/filename).write_text('@echo off\n"%~dp0DotAbyss.exe" '+arguments+'\npause\n', encoding='ascii', newline='\r\n')
    deps = json.loads((ROOT/'THIRD_PARTY_NOTICES/dependencies.json').read_text(encoding='utf-8'))
    models = {}
    for file in (built/'_internal/rapidocr_onnxruntime/models').glob('*.onnx'):
        models[file.name] = digest(file)
    if len(models) != 3:
        raise RuntimeError('Expected three bundled OCR models')
    info = {'version': VERSION, 'built_at_utc': datetime.now(timezone.utc).isoformat(),
            'source_commit': git_revision(), 'python': sys.version.split()[0],
            'pyinstaller': metadata.version('pyinstaller'), 'platform': 'Windows x64',
            'template_manifest_sha256': digest(ROOT/'assets/templates/manifest.json'),
            'dependency_lock_sha256': digest(ROOT/'requirements-build-win-x64.lock'),
            'ocr_models_sha256': models, 'dependency_versions': {d['name']:d['version'] for d in deps},
            'validation': {'new_game_test': False, 'independent_machine_test': False,
                           'status': 'offline validation only; see VALIDATION.md'},
            'license': 'Dot Abyss noncommercial sharing license 1.0'}
    write_json(release_dir/'release.json', info)
    report_folder = ROOT/'validation-output'
    report_folder.mkdir(exist_ok=True)
    result = subprocess.run([str(release_dir/'DotAbyss.exe'), 'self-test', '--gui-check',
                             '--report', str(report_folder/'frozen-self-test.json')],
                            cwd=output, check=True, capture_output=True, text=True, encoding='utf-8')
    print(result.stdout)
    validation = ROOT/'release/VALIDATION.md'
    if validation.exists():
        shutil.copyfile(validation, release_dir/'VALIDATION.md')
    write_json(release_dir/'file-manifest.json', {p.relative_to(release_dir).as_posix(): digest(p)
               for p in sorted(release_dir.rglob('*')) if p.is_file()})
    subprocess.run([sys.executable,str(ROOT/'scripts/verify_release.py'),str(release_dir),
                    '--report',str(report_folder/'isolated-release.json')],check=True)
    frozen_replay_count=None
    if not args.skip_replay:
        subprocess.run([str(release_dir/'DotAbyss.exe'),'offline-replay',
                        '--samples-dir',str(ROOT/'samples'),
                        '--report',str(report_folder/'frozen-offline-report.json')],
                       cwd=output,check=True)
        replay=json.loads((report_folder/'frozen-offline-report.json').read_text(encoding='utf-8'))
        if not replay or not all(item['pass'] for item in replay):
            raise RuntimeError('Frozen offline replay failed')
        frozen_replay_count=len(replay)
    write_json(release_dir/'validation-results.json',{
        'frozen_self_test':json.loads((report_folder/'frozen-self-test.json').read_text(encoding='utf-8')),
        'isolated_release':json.loads((report_folder/'isolated-release.json').read_text(encoding='utf-8')),
        'frozen_replay_passed':frozen_replay_count,'new_game_test':False,
        'independent_machine_test':False})
    write_json(release_dir/'file-manifest.json',{p.relative_to(release_dir).as_posix():digest(p)
               for p in sorted(release_dir.rglob('*')) if p.is_file() and p.name!='file-manifest.json'})
    binary_zip = output/(release_dir.name+'.zip')
    archive_folder(release_dir, binary_zip)

    source_dir = output/f'DotAbyss-{VERSION}-source'
    source_dir.mkdir()
    source_files = ['app.py','app_paths.py','app_runtime.py','abyss_bot.py','launcher.py',
                    'farm_policy.py','environment_check.py','release_smoke.py','version.py',
                    'verify_offline.py','verify_packaging.py','build_templates.py',
                    'requirements.txt','requirements-win-x64.lock','requirements-build-win-x64.lock',
                    'config.default.json','README.md','LICENSE','CHANGELOG.md','.gitignore','.gitattributes',
                    'run.ps1','启动脚本.cmd']
    for name in source_files:
        shutil.copyfile(ROOT/name, source_dir/name)
    for name in ('assets', 'packaging', 'scripts', 'release', 'THIRD_PARTY_NOTICES'):
        shutil.copytree(ROOT/name, source_dir/name, ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copyfile(release_dir/'release.json', source_dir/'release.json')
    source_zip=output/(source_dir.name+'.zip')
    archive_folder(source_dir, source_zip)
    (output/'SHA256SUMS.txt').write_text(''.join(f'{digest(file)}  {file.name}\n' for file in (binary_zip, source_zip)), encoding='ascii')
    print('Created:', binary_zip, source_zip, sep='\n')


if __name__ == '__main__':
    main()
