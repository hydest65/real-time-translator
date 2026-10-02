# Build with the existing cloud-first environment. Never collect local models or secrets.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
datas = [(str(root / 'frontend'), 'frontend')]
binaries = []
hiddenimports = ['backend.main', 'uvicorn.logging', 'uvicorn.loops.asyncio',
                 'uvicorn.protocols.http.h11_impl', 'uvicorn.protocols.websockets.websockets_impl',
                 'uvicorn.lifespan.on', 'websockets.legacy.server', '_cffi_backend']
for package in ['azure.cognitiveservices.speech', 'sounddevice', 'soundcard', '_sounddevice_data']:
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
a = Analysis([str(root / 'desktop' / 'backend_worker.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=['torch', 'torchaudio', 'torchvision', 'transformers', 'funasr',
                       'faster_whisper', 'ctranslate2', 'argostranslate', 'scipy',
                       'pandas', 'matplotlib', 'PIL', 'sklearn', 'pyannote', 'opencc',
                       'onnxruntime', 'sentencepiece', 'tensorflow', 'pytest', 'IPython'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='subtitle-backend',
          debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='subtitle-backend')
