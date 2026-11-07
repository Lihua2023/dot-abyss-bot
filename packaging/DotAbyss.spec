from pathlib import Path
import sys
import zipfile
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

root = Path(SPECPATH).parent
datas = collect_data_files('rapidocr_onnxruntime')
tcl_root = Path(sys.base_prefix) / 'tcl'
tcl_extract = root / 'build' / '_tcltk_extracted'
for zip_name, target_dir in (('libtcl*.zip', '_tcl_data'), ('libtk*.zip', '_tk_data')):
    for zpath in tcl_root.glob(zip_name):
        out_dir = tcl_extract / target_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zpath) as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                rel = Path(*Path(member.filename).parts[1:])
                dest = out_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(member))
        datas.append((str(out_dir), target_dir))
for extra_dir in ('tk9.0', 'dde1.4', 'registry1.3'):
    src_dir = tcl_root / extra_dir
    if src_dir.is_dir():
        datas.append((str(src_dir), f'_tcl_data/{extra_dir}'))
binaries = collect_dynamic_libs('onnxruntime')
hidden = collect_submodules('rapidocr_onnxruntime') + ['pyautogui', 'PIL.ImageGrab', 'green_farm', 'green_loot', 'green_farm_policy']
a = Analysis([str(root/'app.py')], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=hidden, hookspath=[], runtime_hooks=[],
             excludes=['pytest', 'IPython', 'matplotlib', 'pandas', 'scipy'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='DotAbyss',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='DotAbyss')
