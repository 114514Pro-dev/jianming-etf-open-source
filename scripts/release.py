"""Build and package a clean committed main; never build a dirty production release."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]

def run(*args):
    return subprocess.check_output(args, cwd=ROOT)

def digest(file):
    value = hashlib.sha256()
    with file.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): value.update(chunk)
    return value.hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    if run('git','branch','--show-current').decode().strip() != 'main':
        raise SystemExit('Production builds require main')
    if run('git','status','--porcelain').strip():
        raise SystemExit('Production builds require a clean checkout')
    revision = run('git','rev-parse','HEAD').decode().strip()
    project = 'jianming-etf'
    output = options.output.resolve() / (project + '-' + revision[:12])
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source'; source.mkdir()
    tree = run('git','-c','core.autocrlf=false','archive','--format=tar','HEAD','production')
    with tarfile.open(fileobj=io.BytesIO(tree)) as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if not parts or parts[0] != 'production': raise ValueError('Unexpected archive prefix')
            member.name = '/'.join(parts[1:])
            if not member.name: continue
            if not member.isfile() and not member.isdir(): raise ValueError('Special archive member')
            archive.extract(member, source, filter='data')
    files = []
    for file in sorted(source.rglob('*')):
        if file.is_file():
            files.append({'path': file.relative_to(source).as_posix(), 'bytes': file.stat().st_size, 'sha256': digest(file)})
    manifest = {'schemaVersion': 1, 'kind': 'aliyun-portable-release', 'status': 'preproductionCandidate',
        'gitRevision': revision, 'credentialsCopied': False, 'learningDataCopied': False,
        'originalPdfCopied': False, 'files': files}
    (source / 'release-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf8')
    source_archive = output / 'source.tar.gz'
    with tarfile.open(source_archive, 'w:gz') as archive:
        for file in sorted(source.rglob('*')):
            archive.add(file, arcname=file.relative_to(source).as_posix(), recursive=False)
    tag = project + ':main-' + revision[:12]
    dockerfile = source / 'Dockerfile'
    subprocess.run(['docker','build','--progress','plain','--build-arg','GIT_REVISION='+revision,
        '--build-arg','SOURCE_ARCHIVE_SHA='+digest(source_archive),
        '-f',str(dockerfile),'-t',tag,str(source)],check=True,cwd=ROOT)
    image = json.loads(run('docker','image','inspect',tag))[0]
    if image['Config']['Labels'].get('org.opencontainers.image.revision') != revision:
        raise ValueError('Image revision differs from committed source')
    if image['Config']['Labels'].get('io.project.source-archive-sha256') != digest(source_archive):
        raise ValueError('Image source archive differs from verified source')
    if image['Os'] != 'linux' or image['Architecture'] != 'amd64':
        raise ValueError('Expected Linux amd64 release')
    image_archive = output / 'image.tar.gz'
    process = subprocess.Popen(['docker','save',tag],stdout=subprocess.PIPE,cwd=ROOT)
    with gzip.open(image_archive,'wb',compresslevel=3) as target:
        for chunk in iter(lambda:process.stdout.read(1024*1024), b''): target.write(chunk)
    if process.wait(): raise RuntimeError('Image export failed')
    receipt = {'project':project,'gitRevision':revision,'imageTag':tag,'imageId':image['Id'],
        'sourceSha256':digest(source_archive),'imageArchiveSha256':digest(image_archive),
        'shipScriptSha256':digest(ROOT/'scripts/ship.py')}
    (output/'release.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'releaseReceipt':str(output/'release.json'),**receipt}))

if __name__ == '__main__': main()
