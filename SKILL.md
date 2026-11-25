---
name: modrinth
description: Search Modrinth mods by loader and Minecraft version, inspect full version records, files and dependencies, and perform explicitly requested project or release API actions.
---

# Modrinth

Use `python3 scripts/mr.py` from this skill directory. It uses only Python's
standard library. Public reads work without a token.

```sh
python3 scripts/mr.py search sodium --loader fabric --game-version 1.21.1
python3 scripts/mr.py versions sodium --loader fabric --game-version 1.21.1
python3 scripts/mr.py api GET /project/sodium
```

Use the returned version records to check loaders, game versions, dependencies,
file hashes and download URLs. A search match alone does not prove compatibility.
Search responses retain API pagination fields. Use `api GET` with the API's
pagination parameters for later pages.

For account actions, use `MODRINTH_TOKEN` or the same key in the private file
`~/.config/modrinth/credentials.env` with mode 0600. Do not print the file or put
tokens in commands, chat, URLs or repository files. Requests are restricted to
the Modrinth API origin, verify TLS and refuse redirects.

```sh
python3 scripts/mr.py whoami
python3 scripts/mr.py multipart /version --metadata /private/release.json --file jar=/path/mod.jar
python3 scripts/mr.py api PATCH /project/PROJECT --json-file /private/edit.json
```

Writes are previews unless `--execute` is supplied. For an authorized write,
check the target and payload, then execute once. After a timeout, reconcile
server state before retrying; the helper does not retry writes. Responses redact
credential fields and the current token. `--output FILE` saves the redacted JSON.

`--api-version 3` selects v3, including project disclosures where supported.
Before publishing, check current API schemas, platform rules, project permissions,
version compatibility and actual development provenance. Do not infer publication
rights from a successful identity check or replace a user's chosen visibility.
