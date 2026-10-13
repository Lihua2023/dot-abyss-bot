"""Preserve installed dependency license texts and explicit upstream fallbacks."""
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT/'THIRD_PARTY_NOTICES'
FALLBACK = {
    'flatbuffers': 'https://raw.githubusercontent.com/google/flatbuffers/v25.12.19/LICENSE',
    'mouseinfo': 'https://raw.githubusercontent.com/asweigart/mouseinfo/master/LICENSE.txt',
    'pygetwindow': 'https://raw.githubusercontent.com/asweigart/PyGetWindow/master/LICENSE.txt',
    'rapidocr-onnxruntime': 'https://raw.githubusercontent.com/RapidAI/RapidOCR/main/LICENSE',
}


def fetch(url, path):
    with urllib.request.urlopen(url, timeout=60) as response:
        content = response.read()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {'url': url, 'sha256': hashlib.sha256(content).hexdigest()}


def main():
    DEST.mkdir(exist_ok=True)
    summary = []
    sources = {}
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name = dist.metadata['Name']
        if name.lower() == 'pip':
            continue
        folder = DEST/f'{name}-{dist.version}'
        folder.mkdir(exist_ok=True)
        license_files = []
        for file in dist.files or []:
            basename = Path(str(file)).name.lower()
            if not any(word in basename for word in ('license', 'licence', 'copying', 'notice', 'copyright', 'authors')):
                continue
            source = Path(dist.locate_file(file))
            if not source.is_file() or source.suffix in ('.py', '.pyc'):
                continue
            # Preserve nested notices without allowing paths outside the destination.
            target = folder.joinpath(*[part for part in Path(str(file)).parts if part not in ('..', '.')])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            license_files.append(target.relative_to(DEST).as_posix())
        if not license_files:
            url = FALLBACK.get(name.lower())
            if not url:
                raise RuntimeError('Missing license text: '+name)
            target = folder/'LICENSE.upstream.txt'
            sources[name] = fetch(url, target)
            license_files.append(target.relative_to(DEST).as_posix())
        record = {'name': name, 'version': dist.version,
                  'license': dist.metadata.get('License-Expression') or dist.metadata.get('License'),
                  'homepage': dist.metadata.get('Home-page'),
                  'project_urls': dist.metadata.get_all('Project-URL') or [],
                  'license_files': license_files}
        (folder/'metadata.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        summary.append(record)
    python_folder=DEST/'Python'
    python_folder.mkdir(exist_ok=True)
    shutil.copyfile(Path(sys.base_prefix)/'LICENSE.txt', python_folder/'LICENSE.txt')
    for folder_name in ('tcl8.6', 'tk8.6'):
        source=Path(sys.base_prefix)/'tcl'/folder_name/'license.terms'
        if source.exists():
            shutil.copyfile(source, python_folder/(folder_name+'-license.terms'))
    if not (python_folder/'tcl8.6-license.terms').exists():
        sources['Tcl 8.6.12']=fetch('https://raw.githubusercontent.com/tcltk/tcl/core-8-6-12/license.terms', python_folder/'tcl8.6-license.terms')
    sources['PaddleOCR models']=fetch('https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/main/LICENSE', DEST/'PaddleOCR-LICENSE.txt')
    (DEST/'dependencies.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (DEST/'upstream-sources.json').write_text(json.dumps(sources, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Preserved license texts for {len(summary)} distributions, Python and OCR models.')


if __name__ == '__main__':
    main()
