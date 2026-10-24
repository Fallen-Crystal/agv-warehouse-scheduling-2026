from pathlib import Path
import hashlib,json,zipfile
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'MANIFEST.sha256.json').read_text(encoding='utf-8'))
for name,digest in manifest.items():
    p=root/name
    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError(name)
for p in root.rglob('*.zip'):
    if '_runtime' not in p.parts:
        with zipfile.ZipFile(p) as z:
            if z.testzip():raise ValueError(str(p))
print(json.dumps(dict(files_verified=len(manifest),zip_crc_valid=True)))
