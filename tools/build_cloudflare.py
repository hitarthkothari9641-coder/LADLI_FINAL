"""Package only LADLI's public HTML/assets and static admin UI, never secrets."""
import argparse
from pathlib import Path
import shutil
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--production', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / '.dist' / 'cloudflare'
    if (root / '.dist').is_symlink() or output.is_symlink():
        raise SystemExit('Refusing a symlinked build target.')
    if output.resolve() != root / '.dist' / 'cloudflare':
        raise SystemExit('Build output is outside the expected generated directory.')
    if output.exists():
        print('Verified generated build target:', output.resolve())
        shutil.rmtree(output)
    shutil.copytree(root / 'site', output)
    shutil.copytree(root / 'admin', output / 'admin')
    if not args.production:
        (output / 'robots.txt').write_text('User-agent: *\nDisallow: /\n', encoding='utf-8')
    common = '  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n'
    (output / '_headers').write_text('/*\n' + common +
        ('' if args.production else '  X-Robots-Tag: noindex, nofollow\n'), encoding='utf-8')
    archive = root / '.dist' / 'ladli-cloudflare-preview.zip'
    if args.production:
        archive = archive.with_name('ladli-cloudflare-production.zip')
    files = [p for p in output.rglob('*') if p.is_file()]
    for path in files:
        if path.name.startswith('.env') or path.suffix in ('.py', '.sql', '.toml', '.pem', '.key'):
            raise SystemExit('Unexpected private or server-side file in static build.')
        if path.stat().st_size > 25 * 1024 * 1024:
            raise SystemExit('An asset exceeds the free static hosting file-size limit.')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, path.relative_to(output).as_posix())
    print('Packaged', len(files), 'static files:', archive)


if __name__ == '__main__':
    main()
