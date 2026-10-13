from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

root = Path(SPECPATH).parent
datas = collect_data_files('rapidocr_onnxruntime')
binaries = collect_dynamic_libs('onnxruntime')
hidden = collect_submodules('rapidocr_onnxruntime') + ['pyautogui', 'PIL.ImageGrab']
a = Analysis([str(root/'app.py')], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=hidden, hookspath=[], runtime_hooks=[],
             excludes=['pytest', 'IPython', 'matplotlib', 'pandas', 'scipy'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='DotAbyss',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='DotAbyss')
