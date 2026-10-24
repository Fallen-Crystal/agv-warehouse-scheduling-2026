"""Restore and verify the original byte-for-byte requests, without network access."""
from pathlib import Path
import gzip,hashlib,json
root=Path(__file__).resolve().parent
m=json.loads((root/'source-manifest.json').read_text(encoding='utf-8'))
gz=root/'raw/2_orders.json.gz'
assert hashlib.sha256(gz.read_bytes()).hexdigest()==m['compressed_orders_sha256']
data=gzip.decompress(gz.read_bytes());p=root/'raw/2_orders.json'
assert hashlib.sha256(data).hexdigest()==m['files'][p.name]['sha256']
if p.exists() and p.read_bytes()!=data:raise ValueError('Refuse to overwrite different data')
if not p.exists():p.write_bytes(data)
for name,expected in m['files'].items():
    assert hashlib.sha256((root/'raw'/name).read_bytes()).hexdigest()==expected['sha256'],name
print(json.dumps(dict(original_rows=len(json.loads(data)),all_original_hashes_valid=True)))
