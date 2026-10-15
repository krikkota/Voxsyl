#!/usr/bin/env python3
"""Project-only signing identity for local builds; never grants macOS access."""
from pathlib import Path
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import secrets
import shlex
import subprocess
import tempfile

APP = Path(__file__).resolve().parent
ROOT = APP.parent
STORE = ROOT / '.local/dev-signing'
IDENTITY = STORE / 'identity.json'
BUNDLE_ID = 'org.voxsyl.prototype'


def run(*args, capture=False):
    # Keep secret-bearing command arguments out of diagnostics.
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        detail = ': '+result.stderr.strip() if Path(args[0]).name == 'codesign' else ''
        raise RuntimeError(f'{Path(args[0]).name} {args[1]} failed ({result.returncode}){detail}')
    return result.stdout.strip() if capture else None


def private_write(path, text):
    with open(path, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as handle:
        handle.write(text)


def search_list():
    return shlex.split(run('/usr/bin/security', 'list-keychains', '-d', 'user', capture=True))


def initialize():
    if IDENTITY.exists():
        return load_identity()
    if STORE.exists() and any(STORE.iterdir()):
        raise RuntimeError('Signing setup is incomplete. Preserve the existing files; do not generate a replacement identity automatically.')
    STORE.mkdir(parents=True, mode=0o700, exist_ok=True)
    STORE.chmod(0o700)
    keychain = STORE / 'voxsyl-dev.keychain-db'
    password = secrets.token_urlsafe(36)
    private_write(STORE / 'keychain-password', password)
    config = STORE / 'openssl.cnf'
    private_write(config, '[req]\nprompt = no\ndistinguished_name = name\nx509_extensions = signing\n'
                  '[name]\nCN = Voxsyl Local Development\n'
                  '[signing]\nbasicConstraints = critical,CA:FALSE\nkeyUsage = critical,digitalSignature\n'
                  'extendedKeyUsage = critical,codeSigning\nsubjectKeyIdentifier = hash\n')
    key, cert, p12 = STORE/'key.pem', STORE/'certificate.pem', STORE/'identity.p12'
    previous_umask = os.umask(0o077)
    try:
        run('/usr/bin/openssl', 'req', '-new', '-x509', '-newkey', 'rsa:3072', '-nodes', '-sha256',
            '-days', '3650', '-config', str(config), '-keyout', str(key), '-out', str(cert))
        run('/usr/bin/openssl', 'pkcs12', '-export', '-inkey', str(key), '-in', str(cert),
            '-name', 'Voxsyl Local Development', '-passout', 'file:'+str(STORE/'keychain-password'), '-out', str(p12))
        # security create-keychain appends to the user search list. Remove only
        # our new keychain immediately; preserve every other entry and default.
        before = search_list()
        try:
            run('/usr/bin/security', 'create-keychain', '-p', password, str(keychain))
        finally:
            after = search_list()
            retained = [p for p in after if Path(p).resolve() != keychain.resolve()]
            if retained != after:
                run('/usr/bin/security', 'list-keychains', '-d', 'user', '-s', *retained)
        assert search_list() == before, 'Keychain search list changed concurrently; inspect before continuing.'
        run('/usr/bin/security', 'unlock-keychain', '-p', password, str(keychain))
        run('/usr/bin/security', 'import', str(p12), '-k', str(keychain), '-P', password,
            '-f', 'pkcs12', '-x', '-T', '/usr/bin/codesign')
        # Applies only to this isolated new keychain, not the user's identities.
        run('/usr/bin/security', 'set-key-partition-list', '-S', 'apple-tool:', '-s', '-k', password, str(keychain))
        der = subprocess.check_output(['/usr/bin/openssl', 'x509', '-in', str(cert), '-outform', 'DER'])
        fingerprint = hashlib.sha1(der).hexdigest().upper()
        value = {'schema_version':1, 'bundle_id':BUNDLE_ID, 'certificate_sha1':fingerprint,
                 'certificate_sha256':hashlib.sha256(der).hexdigest(), 'keychain':str(keychain),
                 'requirement':f'identifier "{BUNDLE_ID}" and certificate leaf = H"{fingerprint}"',
                 'scope':'Local project signing only. No system trust, login-keychain import, permission grants or notarization.'}
        private_write(IDENTITY, json.dumps(value, indent=2)+'\n')
    finally:
        os.umask(previous_umask)
        # Keep the non-extractable key in the dedicated keychain only.
        for path in [key, p12]:
            if path.exists(): path.unlink()
    return load_identity()


def load_identity():
    if not IDENTITY.exists():
        raise RuntimeError('Local signing identity missing. Run python3 app/dev_signing.py --initialize once before building.')
    value = json.loads(IDENTITY.read_text())
    if value['bundle_id'] != BUNDLE_ID or Path(value['keychain']).resolve() != (STORE/'voxsyl-dev.keychain-db').resolve():
        raise RuntimeError('Unexpected signing identity configuration.')
    return value


@contextmanager
def active_identity():
    identity = load_identity()
    password = (STORE/'keychain-password').read_text()
    run('/usr/bin/security', 'unlock-keychain', '-p', password, identity['keychain'])
    # codesign requires the identity's keychain on the search list even with
    # --keychain. Add it only during signing; no default/trust settings change.
    before = search_list()
    added = identity['keychain'] not in before
    try:
        if added: run('/usr/bin/security', 'list-keychains', '-d', 'user', '-s', *before, identity['keychain'])
        yield identity
    finally:
        if added:
            remaining = [p for p in search_list() if Path(p).resolve() != Path(identity['keychain']).resolve()]
            run('/usr/bin/security', 'list-keychains', '-d', 'user', '-s', *remaining)


def sign(bundle):
    with active_identity() as identity:
        run('/usr/bin/codesign', '--force', '--sign', identity['certificate_sha1'], '--keychain', identity['keychain'],
            '--timestamp=none', '--preserve-metadata=entitlements,flags',
            '--requirements', '=designated => '+identity['requirement'], str(bundle))
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', '-R', '='+identity['requirement'], str(bundle))
    actual = subprocess.run(['/usr/bin/codesign', '-d', '-r-', str(bundle)], capture_output=True, text=True, check=True)
    requirement_dump = actual.stdout + actual.stderr
    if 'cdhash H' in requirement_dump or identity['requirement'].lower() not in requirement_dump.lower():
        raise RuntimeError('Bundle did not retain its certificate-bound designated requirement.')
    return identity


def verify_update_identity():
    identity = load_identity()
    with active_identity(), tempfile.TemporaryDirectory(prefix='voxsyl-signing-', dir=STORE) as temp:
        directory = Path(temp)
        results=[]
        for index in [1, 2]:
            source, executable = directory/f'probe-{index}.c', directory/f'probe-{index}'
            source.write_text(f'int main(void) {{ return {index}; }}\n')
            run('/usr/bin/clang', str(source), '-o', str(executable))
            # Identifier is fixed while executable contents intentionally differ.
            run('/usr/bin/codesign', '--sign', identity['certificate_sha1'], '--keychain', identity['keychain'],
                '--identifier', BUNDLE_ID, '--timestamp=none', '--requirements', '=designated => '+identity['requirement'], str(executable))
            run('/usr/bin/codesign', '--verify', '--strict', '-R', '='+identity['requirement'], str(executable))
            details=subprocess.run(['/usr/bin/codesign','-d','-r-','--verbose=4',str(executable)],capture_output=True,text=True,check=True)
            dump=details.stdout+details.stderr
            results.append({'cdhash':next(line.split('=',1)[1] for line in dump.splitlines() if line.startswith('CDHash=')),
                            'requirement':next(line for line in dump.splitlines() if 'designated =>' in line)})
        assert results[0]['cdhash'] != results[1]['cdhash'], 'Probe payloads must differ.'
        assert results[0]['requirement'] == results[1]['requirement'], 'Update identity must remain stable.'
        assert 'certificate leaf' in results[0]['requirement'], 'Identity must remain tied to the signing certificate.'
        return {'scope':'Two distinct signed probe binaries, neither executed. Verifies stable certificate-bound identity, not macOS permission retention.',
                'certificate_sha256':identity['certificate_sha256'], 'probes':results, 'passed':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--initialize',action='store_true')
    parser.add_argument('--verify-update-identity',action='store_true')
    args=parser.parse_args()
    if args.initialize:
        initialize()
        print('Project-only signing identity ready. Existing identities and macOS permissions were not changed.')
    if args.verify_update_identity:
        report=verify_update_identity()
        path=ROOT/'outputs/dev-signing-verification.json'
        path.write_text(json.dumps(report,indent=2)+'\n')
        print(path)
    if not args.initialize and not args.verify_update_identity: parser.print_help()


if __name__=='__main__':
    try: main()
    except (RuntimeError, AssertionError) as error: raise SystemExit(str(error))
