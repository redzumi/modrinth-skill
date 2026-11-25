# modrinth-skill

Search Minecraft mods and inspect versions, files and dependencies from the
Modrinth API. Includes a Python CLI and an agent skill. No MCP server is needed.

Requires Python 3.11 or newer. No Python packages need installing.

## Find mods

```sh
python3 scripts/mr.py search sodium --loader fabric --game-version 1.21.1
python3 scripts/mr.py versions sodium --loader fabric --game-version 1.21.1
python3 scripts/mr.py api GET /project/sodium
```

Search and other public reads work without credentials. Responses keep the API's
fields, including version dependencies, file hashes and download URLs. Check
loader and game-version compatibility before downloading or recommending a mod.

## Use with an agent

Install this folder as the `modrinth` skill, or point your agent at
[SKILL.md](SKILL.md). Keep `scripts/` alongside it.

## Publish or update your projects

Create a [Modrinth token](https://modrinth.com/settings/account) with the scopes
needed for your action. Store `MODRINTH_TOKEN` in your environment or in
`~/.config/modrinth/credentials.env` with mode 0600. Keep credentials out of Git.

```sh
python3 scripts/mr.py whoami
python3 scripts/mr.py multipart /version --metadata /private/release.json --file jar=/path/mod.jar
python3 scripts/mr.py multipart /version --metadata /private/release.json --file jar=/path/mod.jar --execute
python3 scripts/mr.py api PATCH /project/PROJECT --json-file /private/edit.json
```

Writes default to a preview. Add `--execute` to send an authorized write.
Multipart metadata must use the API schema, with `file_parts` matching the file
field names. The CLI supports raw bodies, JSON, multipart uploads, and v2/v3 API
paths. Run `python3 scripts/mr.py --help` for options.

Requests use HTTPS and stay on `api.modrinth.com`; redirects are refused. Writes
are never retried automatically. Check server state after a timeout before
retrying a publication. Output redacts credential fields and the current token;
use `--output FILE` to save it. It is not a general-purpose anonymizer.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests use fake tokens, generated files and mocked requests. They do not publish
mods or contact your account.

[MIT](LICENSE). This is an independent client for the
[Modrinth API](https://docs.modrinth.com/), not an official Modrinth project.
