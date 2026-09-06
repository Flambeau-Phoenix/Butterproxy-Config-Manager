# Butter Config Service

A Go backend service for remotely managing **Butter / Butterproxy configuration** over SSH.

`butter_config_service.go` provides a local HTTP API that allows a desktop application to:

- Connect to a remote Linux host over SSH.
- Load and inspect Butter configuration.
- Browse remote directories.
- Discover OpenAI-compatible models from the remote machine.
- Add or update Butter providers.
- Update API-key environment variables.
- Delete providers and associated model routes.
- Edit raw Butter YAML.
- Restart the remote Butter systemd service.

The service is designed as a backend component rather than a standalone GUI application.

---

# Overview

The service acts as a bridge between a local desktop frontend and a remote Butter installation:

```text
Desktop UI
    |
    | HTTP / JSON
    v
Butter Config Service
    |
    | SSH
    v
Remote Linux Server
    |
    +-- /etc/butter/config.yaml
    |
    +-- /opt/eh-stack/config/eh.env
    |
    +-- OpenAI-compatible providers
    |
    +-- systemd
```

Model discovery is performed **through the SSH connection**, which means services bound only to the remote machine's loopback interface can still be queried.

For example:

```text
Desktop
   |
   | SSH
   v
Remote Host
   |
   +--> http://127.0.0.1:11434/v1
        Ollama
```

The Ollama endpoint does not need to be publicly exposed.

---

# Requirements

## Go

The service uses Go and requires these external packages:

```text
go.yaml.in/yaml/v4
golang.org/x/crypto/ssh
```

Install them in the containing Go module with:

```bash
go get go.yaml.in/yaml/v4
go get golang.org/x/crypto/ssh
```

The service also uses the Go standard library for:

- HTTP.
- JSON.
- SSH transport setup.
- URL validation.
- Base64 encoding.
- Networking.
- File access.
- Sorting.
- Timeouts.

---

# Integration

This file uses:

```go
package main
```

and is intended to be compiled as part of a larger Go application.

The primary HTTP entry point is:

```go
func handleButterSSH(w http.ResponseWriter, r *http.Request)
```

Your host application should register it with an HTTP server, for example:

```go
http.HandleFunc("/api/butter/ssh", handleButterSSH)
```

The exact route is up to the containing application.

The file also expects the surrounding application to provide the helper:

```go
remoteIP(r)
```

used to determine whether a request originated from localhost.

---

# Local-Only HTTP Access

The SSH-management endpoint is intentionally restricted to loopback callers.

Allowed addresses:

```text
127.0.0.1
::1
```

Requests from other addresses receive:

```text
403 Forbidden
```

with the message:

```text
custom SSH management is available only from the local desktop
```

This is important because requests can contain:

- SSH passwords.
- Private-key paths.
- Private-key passphrases.
- Sudo passwords.
- Provider API keys.
- Remote configuration contents.

The HTTP layer also enables CORS:

```text
Access-Control-Allow-Origin: *
```

so the localhost restriction is an important part of the service's security boundary.

---

# HTTP Method

The endpoint accepts:

```text
POST
OPTIONS
```

`OPTIONS` is handled for CORS preflight requests.

Other methods return:

```text
405 Method Not Allowed
```

---

# Request Size Limit

Incoming HTTP requests are limited to approximately:

```text
2 MiB
```

The same limit is applied to remote documents handled by the service.

This is defined by:

```go
const butterSSHMaxDocumentBytes = 2 << 20
```

---

# Request Format

Requests use JSON.

The high-level structure is:

```json
{
  "action": "test",
  "connection": {},
  "provider": {},
  "path": "",
  "rawYaml": ""
}
```

Not every field is required for every action.

---

# SSH Connection Object

Remote connection details are supplied through:

```json
{
  "host": "192.168.1.100",
  "port": 22,
  "username": "user",
  "authMethod": "key",
  "password": "",
  "keyPath": "~/.ssh/id_ed25519",
  "keyPassphrase": "",
  "useSudo": true,
  "sudoPassword": "",
  "configPath": "/etc/butter/config.yaml",
  "envPath": "/opt/eh-stack/config/eh.env",
  "service": "butter"
}
```

## Fields

| Field | Purpose |
| --- | --- |
| `host` | SSH hostname or IP |
| `port` | SSH port; defaults to `22` |
| `username` | Remote SSH username |
| `authMethod` | Authentication type |
| `password` | SSH password |
| `keyPath` | Local private-key path |
| `keyPassphrase` | Private-key passphrase |
| `useSudo` | Execute file commands through sudo |
| `sudoPassword` | Password used for sudo |
| `configPath` | Remote Butter YAML path |
| `envPath` | Remote environment-file path |
| `service` | Butter systemd service |

---

# SSH Authentication

The service currently supports two effective authentication paths.

## Private Key

Use:

```json
{
  "authMethod": "key",
  "keyPath": "~/.ssh/id_ed25519"
}
```

Encrypted private keys can provide:

```json
{
  "keyPassphrase": "..."
}
```

`~/` paths are expanded using the local user's home directory before the key is loaded.

## Password

Any authentication mode other than `"key"` falls back to password authentication.

Example:

```json
{
  "authMethod": "password",
  "password": "..."
}
```

A missing password produces an error.

---

# SSH Host Keys

The service calculates the server's SHA-256 SSH key fingerprint and returns it to the caller.

Example connection-test response:

```json
{
  "status": "ok",
  "message": "SSH connection established",
  "fingerprint": "SHA256:..."
}
```

## Important Security Behavior

The current implementation **records the SSH server fingerprint but does not verify it against a known-hosts file**.

The host-key callback accepts the presented server key and stores its fingerprint for display.

That means the frontend should not treat the current SSH connection behavior as equivalent to normal `known_hosts` verification.

For deployments where the service crosses an untrusted network, host-key verification should be added before relying on the service for sensitive administration.

---

# Supported Actions

The API currently supports:

```text
test
load
list
discover
save_provider
delete_provider
save_raw
restart
```

Each action establishes an SSH connection, performs the requested operation, returns JSON, and closes the connection.

---

# `test`

Tests the SSH connection.

## Request

```json
{
  "action": "test",
  "connection": {
    "host": "192.168.1.100",
    "port": 22,
    "username": "user",
    "authMethod": "key",
    "keyPath": "~/.ssh/id_ed25519"
  }
}
```

## Response

```json
{
  "status": "ok",
  "message": "SSH connection established",
  "fingerprint": "SHA256:..."
}
```

---

# `load`

Loads the remote Butter configuration.

Default configuration path:

```text
/etc/butter/config.yaml
```

Request:

```json
{
  "action": "load",
  "connection": {
    "host": "192.168.1.100",
    "username": "user",
    "authMethod": "key",
    "keyPath": "~/.ssh/id_ed25519"
  }
}
```

The response contains a parsed configuration summary together with the raw YAML.

---

# Configuration Summary

Loaded configurations are summarized into a response resembling:

```json
{
  "status": "ok",
  "config_path": "/etc/butter/config.yaml",
  "default_provider": "openrouter",
  "providers": [],
  "provider_count": 2,
  "route_count": 24,
  "raw_yaml": "...",
  "butter_reload_seconds": 5
}
```

Each provider contains information such as:

```json
{
  "name": "openrouter",
  "base_url": "https://openrouter.ai/api/v1",
  "key_reference": "${OPENROUTER_API_KEY}",
  "has_key": true,
  "is_default": true,
  "models": [
    "openai/gpt-5"
  ],
  "route_count": 1
}
```

Actual inline API-key values are not returned in the public summary.

Instead they are represented as:

```text
configured
```

Environment references such as:

```text
${OPENROUTER_API_KEY}
```

are preserved.

---

# `list`

Lists a remote directory.

Example:

```json
{
  "action": "list",
  "path": "/etc/butter",
  "connection": {
    "...": "..."
  }
}
```

Response entries contain:

```json
{
  "name": "config.yaml",
  "path": "/etc/butter/config.yaml",
  "isDir": false,
  "size": 4821
}
```

Directories are sorted before files.

Within each group, entries are sorted by name.

Only absolute Linux paths are accepted.

For example:

```text
/etc/butter
/opt/eh-stack/config
/home/user
```

Relative paths are rejected.

---

# `discover`

Discovers models from an OpenAI-compatible provider from the perspective of the remote SSH host.

Provider input:

```json
{
  "name": "ollama",
  "baseUrl": "http://127.0.0.1:11434/v1",
  "apiKey": ""
}
```

The service requests:

```text
GET <baseUrl>/models
```

For example:

```text
GET http://127.0.0.1:11434/v1/models
```

The expected API response follows the OpenAI-compatible model format:

```json
{
  "data": [
    {
      "id": "qwen3:8b"
    },
    {
      "id": "embeddinggemma"
    }
  ]
}
```

Successful response:

```json
{
  "status": "ok",
  "models": [
    "embeddinggemma",
    "qwen3:8b"
  ],
  "model_count": 2
}
```

Duplicate model IDs are removed and the resulting list is sorted.

---

# Remote HTTP Through SSH

Provider model discovery does not run from the desktop application's normal network interface.

Instead the service installs an HTTP transport whose connection is created using:

```go
client.Dial(...)
```

from the active SSH connection.

Conceptually:

```text
HTTP Client
    |
    v
SSH client.Dial()
    |
    v
Remote network namespace
    |
    v
Provider /models
```

This makes remote loopback providers usable without SSH port forwarding.

---

# Authentication for Provider Discovery

Provider API keys are resolved in this order:

```text
Explicit provider APIKey
        ↓
Existing provider key
        ↓
Environment-variable reference
        ↓
Remote environment file
```

Keys with these special values are not sent as Bearer tokens:

```text
ollama
none
```

All other non-empty values are sent as:

```http
Authorization: Bearer <key>
```

---

# `save_provider`

Creates or updates a provider and its Butter routes.

Request provider structure:

```json
{
  "name": "openrouter",
  "baseUrl": "https://openrouter.ai/api/v1",
  "apiKey": "...",
  "keyEnv": "OPENROUTER_API_KEY",
  "models": [
    "openai/gpt-5",
    "anthropic/claude-sonnet"
  ],
  "makeDefault": true
}
```

The service:

1. Validates the provider name.
2. Validates the provider URL.
3. Deduplicates and sorts models.
4. Loads the existing Butter YAML.
5. Creates or updates the provider.
6. Updates its API-key environment variable if supplied.
7. Removes stale routes belonging to that provider.
8. Creates routes for the selected models.
9. Optionally makes the provider the default.
10. Rewrites the Butter configuration.
11. Reloads and returns the resulting configuration.

---

# API-Key Environment Variables

When a provider is saved with a new API key, the key is written to the configured remote environment file.

Default:

```text
/opt/eh-stack/config/eh.env
```

If `keyEnv` is provided:

```json
{
  "keyEnv": "OPENROUTER_API_KEY"
}
```

the Butter provider receives:

```yaml
keys:
  - key: ${OPENROUTER_API_KEY}
    weight: 1
```

The environment file receives:

```env
OPENROUTER_API_KEY=actual-secret
```

If no environment-variable name is supplied, one is generated from the provider name.

For:

```text
open-router
```

the generated variable would resemble:

```text
OPEN_ROUTER_API_KEY
```

Hyphens and periods are converted to underscores.

---

# Ollama Handling

New providers using a base URL containing:

```text
:11434
```

are automatically treated as Ollama providers when no API key exists.

Their Butter key is created as:

```yaml
keys:
  - key: ollama
    weight: 1
```

For other new providers, an API key is required.

---

# Butter Routing

Selected models are written under:

```yaml
routing:
  models:
```

Example:

```yaml
routing:
  models:
    qwen3:8b:
      providers:
        - ollama
      strategy: priority
```

When saving a provider, routes previously associated with that provider are removed before the newly selected model routes are generated.

The provider can also become:

```yaml
routing:
  default_provider: ollama
```

when:

```json
{
  "makeDefault": true
}
```

is supplied.

---

# Important Routing Behavior

The current implementation rebuilds each newly selected model route as:

```yaml
providers:
  - provider-name
strategy: priority
```

This means `save_provider` does **not** preserve additional providers previously attached to one of those selected model routes.

For example, this:

```yaml
my-model:
  providers:
    - provider-a
    - provider-b
```

can become:

```yaml
my-model:
  providers:
    - provider-a
  strategy: priority
```

when `provider-a` is saved for that model.

If multi-provider fallback routing is required, this behavior should be considered before using the service to edit those routes.

---

# `delete_provider`

Deletes a Butter provider.

Request:

```json
{
  "action": "delete_provider",
  "provider": {
    "name": "openrouter"
  },
  "connection": {
    "...": "..."
  }
}
```

The service also removes the deleted provider from model routes.

Routes that no longer contain any providers are deleted.

## Default Provider Protection

The service refuses to delete the active default provider.

Another provider must first be selected as the default.

---

# `save_raw`

Writes a complete Butter YAML document.

Example:

```json
{
  "action": "save_raw",
  "rawYaml": "providers:\n  ...",
  "connection": {
    "...": "..."
  }
}
```

Before writing, the service requires the YAML to contain both:

```yaml
providers:
```

and:

```yaml
routing:
  models:
```

The YAML is parsed and re-serialized before being saved.

---

# `restart`

Restarts the remote Butter systemd service.

Request:

```json
{
  "action": "restart",
  "connection": {
    "service": "butter"
  }
}
```

Default service:

```text
butter
```

The equivalent remote operation is:

```bash
sudo systemctl restart butter
```

Successful response:

```json
{
  "status": "ok",
  "message": "Restarted butter"
}
```

Restart operations always force sudo mode.

---

# Sudo Support

When:

```json
{
  "useSudo": true
}
```

is enabled, remote commands are wrapped with:

```bash
sudo -S -p '' sh -c ...
```

The service uses:

```text
sudoPassword
```

when provided.

Otherwise it falls back to the SSH password.

This allows protected locations such as:

```text
/etc/butter/config.yaml
```

to be managed without running the entire remote SSH account as root.

---

# Default Remote Paths

## Butter configuration

```text
/etc/butter/config.yaml
```

## Environment file

```text
/opt/eh-stack/config/eh.env
```

## systemd service

```text
butter
```

All three can be overridden in the request.

---

# Atomic-Style Remote Writes

Configuration files are not directly streamed over the existing destination.

The service:

```text
Encode content
     ↓
Create temporary file beside destination
     ↓
Write decoded content
     ↓
Copy existing file to backup
     ↓
Preserve permissions when possible
     ↓
Move temporary file over destination
```

This reduces the chance of leaving a partially written configuration after an interrupted update.

---

# Backups

Before replacing an existing remote file, the current version is copied to:

```text
<filename>.before-event-horizon
```

For example:

```text
/etc/butter/config.yaml
/etc/butter/config.yaml.before-event-horizon
```

The same write mechanism is used for the environment file.

Note that the backup name is fixed, so repeated writes replace the logical previous-version backup rather than creating timestamped history.

---

# YAML Parsing

Butter configuration is parsed with:

```text
go.yaml.in/yaml/v4
```

The service works primarily with:

```text
providers
routing
routing.models
routing.default_provider
```

A malformed YAML document produces an error such as:

```text
invalid Butter YAML: ...
```

An empty configuration is also rejected.

---

# Provider Validation

Provider names:

- Must not be empty.
- Cannot contain whitespace.
- Cannot contain `/`.
- Cannot contain `\`.

Provider URLs must:

- Parse successfully.
- Use `http://` or `https://`.
- Contain a valid host component.

At least one model must be selected when saving a provider.

Duplicate model IDs are removed automatically.

---

# Remote Path Validation

Remote file and directory paths must:

- Be absolute Linux paths.
- Begin with `/`.
- Contain no null bytes.
- Contain no carriage returns or newlines.

Paths are normalized using Go's POSIX `path.Clean`.

---

# Shell Escaping

Remote paths, service names, and generated command values are shell-quoted before being inserted into SSH command strings.

Single quotes are escaped using a POSIX-compatible quoting pattern.

Additional validation is applied to service names before calling `systemctl`.

---

# Error Responses

Errors are returned as JSON:

```json
{
  "error": "description"
}
```

Typical HTTP status codes include:

| Status | Meaning |
| --- | --- |
| `400` | Invalid JSON request |
| `403` | Caller is not localhost |
| `405` | Unsupported HTTP method |
| `502` | SSH or remote-operation failure |

Examples of operational errors include:

- Missing SSH hostname.
- Missing SSH username.
- Invalid SSH port.
- Missing password.
- Unreadable private key.
- Invalid encrypted key/passphrase.
- SSH connection failure.
- Invalid remote path.
- Invalid Butter YAML.
- Invalid provider URL.
- Empty provider model selection.
- Provider catalog HTTP errors.
- Missing API key.
- Missing provider.
- Attempt to delete the default provider.
- Invalid systemd service name.

---

# Example Frontend Request

```javascript
const response = await fetch("http://127.0.0.1:8080/api/butter/ssh", {
  method: "POST",
  headers: {
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    action: "discover",

    connection: {
      host: "192.168.1.100",
      port: 22,
      username: "myuser",
      authMethod: "key",
      keyPath: "~/.ssh/id_ed25519",
      useSudo: true,
      sudoPassword: "",
      configPath: "/etc/butter/config.yaml",
      envPath: "/opt/eh-stack/config/eh.env",
      service: "butter"
    },

    provider: {
      name: "ollama",
      baseUrl: "http://127.0.0.1:11434/v1",
      apiKey: "",
      keyEnv: "",
      models: [],
      makeDefault: false
    }
  })
});

const result = await response.json();
console.log(result);
```

---

# Typical Desktop Workflow

```text
Open Butter manager
        ↓
Enter SSH connection
        ↓
POST action=test
        ↓
Display SSH fingerprint
        ↓
POST action=load
        ↓
Show providers/routes
        ↓
Choose provider
        ↓
POST action=discover
        ↓
Select models
        ↓
POST action=save_provider
        ↓
Reload configuration
        ↓
POST action=restart
```

---

# Security Considerations

This service can administer remote configuration and credentials, so it should remain a **local desktop service**.

Recommended practices:

- Bind the containing HTTP server to `127.0.0.1` or `::1`.
- Do not expose this endpoint directly to a LAN or the Internet.
- Avoid logging request bodies because they may contain credentials.
- Prefer SSH private-key authentication over reusable passwords.
- Avoid keeping sudo passwords in frontend persistence.
- Store provider secrets in the environment file rather than inline YAML.
- Keep file permissions restricted on remote environment files.
- Add proper SSH known-host verification before using this across untrusted networks.
- Consider adding authentication or a per-session token to the local HTTP API if other local applications should not be able to invoke it.
- Review multi-provider routing behavior before editing configs that use fallback provider lists.

---

# Current Security Caveat: SSH Host Verification

The most significant security limitation in the current implementation is SSH host-key handling.

The current callback:

```text
captures the host fingerprint
but accepts the key presented by the server
```

It does not currently compare the presented key against:

```text
~/.ssh/known_hosts
```

or another trusted fingerprint store.

Therefore the fingerprint is useful for display and manual verification, but the service does not currently prevent a man-in-the-middle SSH server from being accepted.

A future implementation should use strict host-key validation.

---

# Current Behavioral Caveat: Provider Routes

When saving a provider, selected model routes are recreated with only that provider.

If Butter configurations depend on:

```yaml
providers:
  - primary
  - fallback
```

for the same model, the current `save_provider` behavior can remove the fallback relationship.

This service is therefore best suited to configurations where each model route is intentionally owned by one provider, unless the routing-write logic is extended.

---

# File Scope

`butter_config_service.go` contains the remote Butter management layer.

It does **not** define:

- The desktop UI.
- HTTP server startup.
- Application routing outside this handler.
- Persistent frontend settings.
- Local Butter management.
- A standalone executable workflow.
- Authentication for the local desktop API.
- SSH known-host persistence.

Those responsibilities belong to the surrounding application.

---

# Architecture

```text
┌─────────────────────────┐
│      Desktop UI         │
│                         │
│ Providers / Models /    │
│ SSH Settings / YAML     │
└────────────┬────────────┘
             │
             │ localhost JSON
             ▼
┌─────────────────────────┐
│ Butter Config Service   │
│                         │
│ handleButterSSH()       │
└────────────┬────────────┘
             │
             │ SSH
             ▼
┌─────────────────────────┐
│ Remote Linux Machine    │
│                         │
│ config.yaml             │
│ eh.env                  │
│ systemd                 │
│ local model endpoints   │
└─────────────────────────┘
```

---

# Summary

Butter Config Service provides a compact backend for integrating remote Butter administration into a desktop application.

Its main responsibilities are:

```text
Local HTTP API
      +
SSH transport
      +
Remote model discovery
      +
Butter provider management
      +
routing.models management
      +
Environment-secret management
      +
Safe-ish file replacement + backup
      +
systemd restart
```

It is particularly useful when Butter and local model providers such as Ollama run on another Linux machine while the management interface runs on a desktop computer.