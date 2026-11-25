#!/usr/bin/env python3
"""Modrinth search and publishing CLI; Python standard library only."""
import argparse
import json
import mimetypes
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

PROVIDER = 'modrinth'
ORIGIN = 'https://api.modrinth.com'
PREFIX = '/v2'
ENV_KEY = 'MODRINTH_TOKEN'
AUTH_HEADER = 'Authorization'
CONFIG = Path.home() / '.config' / PROVIDER / 'credentials.env'


def load_token(required=True):
    value = os.environ.get(ENV_KEY)
    if not value and CONFIG.exists():
        if stat.S_IMODE(CONFIG.stat().st_mode) & 0o077:
            raise ValueError('Credential file must have mode 0600: ' + str(CONFIG))
        for line in CONFIG.read_text().splitlines():
            line = line.strip()
            if line.startswith('export '):
                line = line[7:].strip()
            key, sep, raw = line.partition('=')
            if sep and key.strip() == ENV_KEY:
                parts = shlex.split(raw, comments=True)
                if len(parts) != 1:
                    raise ValueError('Expected one non-empty token value in credential file')
                value = parts[0]
    if not value:
        if required:
            raise ValueError('Configure ' + ENV_KEY + ' in ' + str(CONFIG))
        return None
    if '\r' in value or '\n' in value:
        raise ValueError('Invalid token line ending')
    return value


def clean(value, token):
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if re.search(r'(?i)(?:token|secret|password|api.?key|authorization)', k)
                    else clean(v, token)) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v, token) for v in value]
    if isinstance(value, str):
        return value.replace(token, '[REDACTED]') if token else value
    return value


def api_url(path):
    if not path.startswith('/') or path.startswith('//') or '#' in path or '\\' in path:
        raise ValueError('Use an API-relative path starting with one slash')
    parsed = urllib.parse.urlsplit(path)
    if parsed.scheme or parsed.netloc or any(p in ('.', '..') for p in parsed.path.split('/')):
        raise ValueError('External origins and relative path traversal are not accepted')
    query_keys = [key.lower() for key, _ in urllib.parse.parse_qsl(parsed.query)]
    if any(re.search(r'token|secret|api.?key|authorization', key) for key in query_keys):
        raise ValueError('Credentials belong in the private config, never URL parameters')
    return ORIGIN + PREFIX + path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'Redirect refused; credentials stay on the configured origin', headers, fp)


def request(method, path, token, body=None, content_type=None):
    headers = {'Accept': 'application/json', 'User-Agent': 'modrinth-skill/0.1 (local API client)'}
    if token:
        headers[AUTH_HEADER] = token
    if content_type:
        headers['Content-Type'] = content_type
    req = urllib.request.Request(api_url(path), data=body, headers=headers, method=method)
    # HTTPS certificate verification is on. Never automatically retry mutations.
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=60) as response:
        data = response.read()
        if not data:
            return {'http_status': response.status}
        try:
            return json.loads(data)
        except (ValueError, UnicodeDecodeError):
            raise ValueError('Expected JSON response; received ' + response.headers.get('Content-Type', 'unknown content type'))


def multipart(metadata_file, files, metadata_field):
    metadata = json.loads(Path(metadata_file).read_text())
    boundary = 'codex-' + uuid.uuid4().hex
    chunks = []
    def append(name, data, filename=None, content_type='application/json'):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            raise ValueError('Invalid multipart field name')
        disposition = 'Content-Disposition: form-data; name="' + name + '"'
        if filename is not None:
            if any(c in filename for c in '\r\n"'):
                raise ValueError('Invalid upload filename')
            disposition += '; filename="' + filename + '"'
        chunks.append(('--' + boundary + '\r\n' + disposition + '\r\nContent-Type: ' + content_type + '\r\n\r\n').encode())
        chunks.extend((data, b'\r\n'))
    append(metadata_field, json.dumps(metadata).encode())
    fields = []
    for spec in files:
        field, sep, filename = spec.partition('=')
        if not sep:
            raise ValueError('Use --file FIELD=/path/to/file')
        path = Path(filename)
        append(field, path.read_bytes(), path.name, mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        fields.append(field)
    if len(set(fields)) != len(fields) or metadata_field in fields:
        raise ValueError('Multipart fields must be unique')
    if PROVIDER == 'modrinth' and 'file_parts' in metadata and set(metadata['file_parts']) != set(fields):
        raise ValueError('Modrinth file_parts must match the uploaded field names')
    chunks.append(('--' + boundary + '--\r\n').encode())
    return b''.join(chunks), 'multipart/form-data; boundary=' + boundary


def main(argv=None):
    global PREFIX
    parser = argparse.ArgumentParser(description=__doc__)
    if PROVIDER == 'modrinth':
        parser.add_argument('--api-version', choices=['2', '3'], default='2')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('whoami' if PROVIDER == 'modrinth' else 'check-access')
    search = sub.add_parser('search', help='Search Minecraft mods; no token required')
    search.add_argument('query')
    search.add_argument('--loader', help='Mod loader, such as fabric or neoforge')
    search.add_argument('--game-version')
    search.add_argument('--limit', type=int, default=10)
    versions = sub.add_parser('versions', help='Read full version records, files and dependencies')
    versions.add_argument('project')
    versions.add_argument('--loader')
    versions.add_argument('--game-version')
    call = sub.add_parser('api')
    call.add_argument('method', choices=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
    call.add_argument('path')
    payload = call.add_mutually_exclusive_group()
    payload.add_argument('--json-file')
    payload.add_argument('--body-file')
    call.add_argument('--content-type', default='application/octet-stream')
    call.add_argument('--execute', action='store_true', help='Perform an already-authorized mutation instead of dry run')
    call.add_argument('--output', type=Path, help='Save the redacted JSON response')
    multi = sub.add_parser('multipart')
    multi.add_argument('path')
    multi.add_argument('--metadata', required=True)
    multi.add_argument('--metadata-field', default='data' if PROVIDER == 'modrinth' else 'metadata')
    multi.add_argument('--file', action='append', default=[])
    multi.add_argument('--execute', action='store_true')
    multi.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if PROVIDER == 'modrinth':
        PREFIX = '/v' + args.api_version
    token = None
    try:
        if args.command == 'search':
            if not 1 <= args.limit <= 100:
                raise ValueError('Search limit must be between 1 and 100')
            facets = [['project_type:mod']]
            if args.loader:
                facets.append(['categories:' + args.loader])
            if args.game_version:
                facets.append(['versions:' + args.game_version])
            query = urllib.parse.urlencode({'query': args.query, 'limit': args.limit, 'facets': json.dumps(facets)})
            token = load_token(required=False)
            result = request('GET', '/search?' + query, token)
        elif args.command == 'versions':
            params = {}
            if args.loader:
                params['loaders'] = json.dumps([args.loader])
            if args.game_version:
                params['game_versions'] = json.dumps([args.game_version])
            path = '/project/' + urllib.parse.quote(args.project, safe='') + '/version'
            if params:
                path += '?' + urllib.parse.urlencode(params)
            token = load_token(required=False)
            result = request('GET', path, token)
        elif args.command in ('whoami', 'check-access'):
            token = load_token()
            result = request('GET', '/user' if PROVIDER == 'modrinth' else '/game/versions', token)
            if PROVIDER == 'modrinth':
                result = {k: result.get(k) for k in ('id', 'username', 'name')}
            else:
                result = {'api_reachable': True, 'game_versions': len(result) if isinstance(result, list) else None,
                          'note': 'Read-endpoint access does not prove upload rights for a project.'}
        else:
            method = 'POST' if args.command == 'multipart' else args.method
            body, content_type = None, None
            if args.command == 'multipart':
                body, content_type = multipart(args.metadata, args.file, args.metadata_field)
            elif args.json_file:
                body, content_type = json.dumps(json.loads(Path(args.json_file).read_text())).encode(), 'application/json'
            elif args.body_file:
                body, content_type = Path(args.body_file).read_bytes(), args.content_type
            url = api_url(args.path)
            if method == 'GET' and body is not None:
                raise ValueError('GET requests do not accept a body')
            if method != 'GET' and not args.execute:
                print(json.dumps({'dry_run': True, 'method': method, 'url': url,
                                  'payload_bytes': len(body or b''), 'content_type': content_type}, indent=2))
                return 0
            token = load_token(required=method != 'GET')
            result = request(method, args.path, token, body, content_type)
        result = clean(result, token)
        text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
        if getattr(args, 'output', None):
            args.output.write_text(text)
            print('Saved redacted JSON response to ' + str(args.output))
        else:
            print(text, end='')
        return 0
    except urllib.error.HTTPError as error:
        try:
            detail = error.read(16384).decode('utf-8', errors='replace')
        finally:
            error.close()
        print(clean('HTTP ' + str(error.code) + ': ' + detail, token), file=sys.stderr)
    except (ValueError, OSError, urllib.error.URLError) as error:
        print(clean(str(error), token), file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
