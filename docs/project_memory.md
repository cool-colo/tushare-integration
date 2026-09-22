# Project Memory

## ClickHouse connectivity

- ClickHouse is accessible outside the Codex sandbox on port `8123`.
- A failed request to `127.0.0.1:8123` from inside the sandbox does not establish that ClickHouse is stopped.
- Project default connection: `clickhouse://127.0.0.1:8123/default`, user `default`, empty password.
- Run ClickHouse queries in an environment with host-network access when validating data.
