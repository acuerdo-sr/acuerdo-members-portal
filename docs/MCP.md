# MCP server

This repository includes a local Model Context Protocol server for AI clients.
It exposes the portal source pages, JSON data, form metadata, subsidy search,
and the static site build command.

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
python scripts/mcp_server.py
```

The server uses STDIO. Do not run it as a normal web server.

## Client config

The repository includes `.mcp.json`:

```json
{
  "mcpServers": {
    "acuerdo-members-portal": {
      "command": "cmd",
      "args": ["/c", "scripts\\run_mcp_server.cmd"]
    }
  }
}
```

On Windows, `scripts/run_mcp_server.cmd` first tries the local Python install at
`%LOCALAPPDATA%\Python\bin\python.exe`, then falls back to `python.exe` or
`py.exe` on `PATH`.

If your MCP client does not use repository-relative paths, replace the wrapper
argument with the absolute path to `scripts/run_mcp_server.cmd`.

## Exposed tools

- `list_pages`: list source pages under `src/pages`.
- `read_page`: read a page by slug, such as `home`, `forms`, or `joseikin-list`.
- `list_data_files`: list JSON datasets under `src/data`.
- `read_data`: read a JSON dataset by name.
- `search_portal`: keyword search across pages and JSON data.
- `list_forms`: list downloadable form metadata.
- `search_forms`: search forms by purpose, category, name, or description.
- `search_subsidies`: search the subsidy quick-reference data.
- `build_site`: run `scripts/build.py` and write `dist/`.
- `fetch_notion_placeholders`: run the current Notion placeholder script.

## Exposed resources

- `portal://summary`
- `portal://data/{name}`
- `portal://page/{slug}`

## Notes

- Secrets are not stored in the MCP config.
- `NOTION_TOKEN` stays in `.env` and is still ignored by git.
- Tool command output is captured and returned to the MCP client, so STDIO JSON
  messages are not polluted by build logs.
