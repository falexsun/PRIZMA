# Content Tracker client start

## Windows

Run:

```bat
setup.bat
```

On a clean computer the script:

- checks Docker Desktop and Docker Compose;
- creates `.env` with generated `POSTGRES_PASSWORD`, `JWT_SECRET` and first admin password;
- saves first admin credentials to `.admin-login.txt`;
- creates local data folders;
- builds and starts `postgres`, `redis`, `api`, `worker`, `beat` and `web`;
- opens http://localhost:5000.

After login as admin, open:

```text
http://localhost:5000/admin/settings
```

Fill the platform settings there if needed:

- `NON-RU proxy` for TikTok, Instagram and Telegram routing when direct access is unavailable;
- `RU proxy` for Dzen and OK routing when direct access is unavailable;
- `VK User token` or `VK Service token`;
- MAX login in the MAX block.
- network access key or client link if the client uses 3x-ui, VLESS, Hysteria2, Amnezia or another VPN/proxy client.

Proxy and network access fields are optional. If the computer already has working access through its own network or a separately installed VPN client, leave them empty.

## Delivery note

Do not ship a pre-filled local `.env` or `data/postgres` folder to a client unless you intentionally want to keep the existing database and credentials.

For a clean client install, let `setup.bat` create `.env`, `.admin-login.txt` and the database folder.

## Optional default accounts

You can provide real default accounts without committing them to git.

1. Put `account.txt` in the project root, next to `setup.bat`.
2. The file content must be JSON. Use `default_accounts.example.json` as the format reference.
3. Run `setup.bat`.

The setup script copies `account.txt` into the backend build context as `default_accounts.json`, and the backend seed creates users that do not already exist.

Existing users are not overwritten on restart.

## Updating

For later project updates, run from the project root:

```bat
update.bat
```

The update script pulls the latest Git changes, refreshes the local accounts seed copy if `account.txt` is present, rebuilds the Docker images and restarts the containers.

It does not delete `.env`, `.admin-login.txt`, uploaded files or the database folder.
