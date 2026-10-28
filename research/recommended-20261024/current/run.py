"""Verified standalone launcher: recommended gate only; no optional solver needed."""
import hashlib,json,os,subprocess,sys,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
EXPECTED='3a71aa51cf8c6ac5ded1d98444d834f73dff794142b5a5f792ca5b722f868a7b'
def main():
    archive=HERE/'runtime.zip'
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=EXPECTED:
        raise ValueError('Runtime archive changed')
    target=HERE/'_runtime'
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('MANIFEST.sha256.json'))
        if not target.exists():
            for name in z.namelist():
                p=(target/name).resolve()
                if not p.is_relative_to(target.resolve()):raise ValueError('Unsafe archive path')
            target.mkdir()
            z.extractall(target)
        for name,digest in manifest.items():
            p=target/name
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
                raise ValueError('Extracted runtime changed: '+name)
    if '--profile' in sys.argv[1:] or any(x.startswith('--profile=') for x in sys.argv[1:]):
        raise ValueError('Recommended launcher fixes gate; use extracted run_main.py for comparisons')
    env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
    env.pop('PYTHONPATH',None)
    return subprocess.call([sys.executable,str(target/'run_main.py'),*sys.argv[1:]],env=env)
if __name__=='__main__':sys.exit(main())
