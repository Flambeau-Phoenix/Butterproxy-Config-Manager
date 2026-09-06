# Butterproxy Config Manager

A single-file **GUI and CLI configuration manager for Butterproxy**.

`butterproxy_config_manager.py` discovers models from OpenAI-compatible API endpoints, manages Butter's native `providers` and `routing.models` configuration, edits local configurations, and can manage remote Butter installations over SSH/SFTP.

The tool is designed to make adding, updating, and synchronizing model providers considerably easier than maintaining Butter YAML by hand.

## Features

### Provider Management

- Add and update Butter providers.
- Discover available models directly from an OpenAI-compatible `/models` endpoint.
- Select which discovered models should be routed through each provider.
- Set a provider as Butter's default provider.
- Remove providers and clean up their associated model routes.
- Preserve multiple providers for the same model.
- Uses Butter's native `providers` and `routing.models` schema.

### Model Discovery

The manager queries:

```text
<base_url>/models
```

and reads model IDs from the standard OpenAI-compatible response format.

Authentication can use:

- A directly supplied API key.
- An environment-variable reference.
- No authentication.
- Ollama-style local authentication.

### Catalog Synchronization

Existing Butter providers can be queried and their model catalogs synchronized automatically.

Synchronization can:

- Update every configured provider.
- Update only selected providers from the CLI.
- Add newly discovered model routes.
- Remove stale routes.
- Preserve routes belonging to providers that were not synchronized.
- Perform a dry run without modifying the configuration.

### Desktop GUI

The Tkinter GUI provides three main sections:

#### Config & Models

Manage providers and model routes from a graphical interface.

Features include:

- Provider selector.
- Base URL editor.
- API key/environment variable management.
- Model discovery.
- Model filtering.
- Select, clear, and invert visible model selections.
- Default-provider selection.
- No-authentication mode.
- Local or remote model discovery.
- Editable Butter YAML preview.
- YAML validation.
- Local load/save.
- Full catalog synchronization.

#### SSH Remote

Manage a Butter installation on another Linux machine.

Supported authentication methods:

- SSH agent.
- Private key.
- Password.

Remote functionality includes:

- SSH/SFTP connection management.
- Optional host-key enrollment.
- Optional `sudo` access for protected files.
- Remote file browser.
- Load remote Butter configuration.
- Save remote Butter configuration.
- Edit the remote environment file.
- Create backups before replacing files.
- Restart the Butter systemd service.
- Optionally restart Butter immediately after saving.

Saved SSH profiles intentionally exclude passwords, key passphrases, sudo passwords, and other secrets.

#### Endpoint Presets

Built-in presets are included for:

| Provider | Base URL |
| --- | --- |
| Local Ollama | `http://127.0.0.1:11434/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| OpenAI | `https://api.openai.com/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| Together AI | `https://api.together.xyz/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |

Custom endpoint presets can also be saved.

API keys are **not** stored in endpoint presets.

---

## Requirements

The script requires Python and the following packages:

```text
PyYAML
requests
```

SSH/SFTP support additionally requires:

```text
paramiko
```

The graphical interface uses Tkinter.

On many desktop Python installations, Tkinter is already included. On Linux it may need to be installed separately, for example through the distribution's `python3-tk` package.

### Install Python Dependencies

```bash
python -m pip install PyYAML requests
```

For remote SSH management:

```bash
python -m pip install PyYAML requests paramiko
```

---

## Running the Application

The simplest way to start the application is:

```bash
python butterproxy_config_manager.py
```

When no command is specified, the script automatically launches the GUI.

You can also explicitly request it:

```bash
python butterproxy_config_manager.py gui
```

Check the installed version with:

```bash
python butterproxy_config_manager.py --version
```

Current application version:

```text
1.0.0
```

---

# GUI Usage

## Open a Local Configuration

Launch the manager with specific local files:

```bash
python butterproxy_config_manager.py gui \
  --config ./config.yaml \
  --env ./.env
```

The GUI can also load another YAML file after startup.

## Add a Provider

In **Config & Models**:

1. Enter a provider name.
2. Enter its OpenAI-compatible base URL.
3. Configure authentication.
4. Click **Fetch Models**.
5. Select the models you want Butter to expose.
6. Optionally enable **Default provider**.
7. Click **Apply Provider & Routes**.
8. Review the generated YAML.
9. Click **Validate**.
10. Save the configuration.

Changes are first applied to the editable YAML preview, allowing the configuration to be inspected before it is written.

---

## API Keys

API keys can be referenced through environment variables instead of being placed directly in the Butter YAML.

For example:

```env
OPENROUTER_API_KEY=your-api-key
```

The provider can then reference:

```yaml
keys:
  - key: ${OPENROUTER_API_KEY}
    weight: 1
```

When an API key is entered through the GUI together with an environment-variable name, the manager writes the secret to the selected environment file and keeps the environment-variable reference in the Butter configuration.

For endpoints that do not require authentication, enable:

```text
No authentication
```

---

# Butter Configuration Structure

The manager operates on Butter's `providers` and `routing.models` mappings.

A minimal configuration managed by the application resembles:

```yaml
providers:
  ollama:
    base_url: http://127.0.0.1:11434/v1
    keys:
      - key: ollama
        weight: 1

  openrouter:
    base_url: https://openrouter.ai/api/v1
    keys:
      - key: ${OPENROUTER_API_KEY}
        weight: 1

routing:
  default_provider: openrouter

  models:
    qwen3:
      providers:
        - ollama
      strategy: priority

    openai/gpt-5:
      providers:
        - openrouter
      strategy: priority
```

A model may have more than one provider:

```yaml
routing:
  models:
    some-model:
      providers:
        - provider-a
        - provider-b
      strategy: priority
```

When a provider is applied to a model, it is placed at the front of that model's provider list.

---

# CLI

The script also includes CLI commands for automation, scripting, validation, and server-side use.

Available commands:

```text
gui
discover
sync
summary
validate
```

## Discover Models

Query an OpenAI-compatible endpoint and print its model IDs:

```bash
python butterproxy_config_manager.py discover \
  --base-url http://127.0.0.1:11434/v1
```

With an API key:

```bash
python butterproxy_config_manager.py discover \
  --base-url https://openrouter.ai/api/v1 \
  --api-key YOUR_KEY
```

Using an environment variable is preferable for normal use:

```bash
python butterproxy_config_manager.py discover \
  --base-url https://openrouter.ai/api/v1 \
  --api-key-env OPENROUTER_API_KEY
```

The result is printed as JSON.

---

## Validate a Butter Configuration

```bash
python butterproxy_config_manager.py validate \
  --config /etc/butter/config.yaml
```

A valid configuration produces output similar to:

```text
OK: /etc/butter/config.yaml
```

Validation checks that the configuration contains valid provider definitions and a valid `routing.models` mapping.

---

## Show a Redacted Summary

```bash
python butterproxy_config_manager.py summary \
  --config /etc/butter/config.yaml
```

The summary reports information such as:

- Default provider.
- Provider count.
- Route count.
- Provider base URLs.
- Number of routes assigned to each provider.
- Whether the provider is the default.
- A redacted indication of its key configuration.

Raw API keys are not emitted by the summary.

---

## Synchronize Provider Catalogs

Refresh `routing.models` using the model catalogs returned by the configured providers:

```bash
python butterproxy_config_manager.py sync \
  --config /etc/butter/config.yaml \
  --env /opt/eh-stack/config/eh.env
```

By default, all configured providers are synchronized.

### Synchronize Specific Providers

`--provider` may be supplied multiple times:

```bash
python butterproxy_config_manager.py sync \
  --config /etc/butter/config.yaml \
  --env /opt/eh-stack/config/eh.env \
  --provider openrouter \
  --provider ollama
```

### Dry Run

Inspect synchronization results without writing the updated configuration:

```bash
python butterproxy_config_manager.py sync \
  --config /etc/butter/config.yaml \
  --env /opt/eh-stack/config/eh.env \
  --dry-run
```

### Disable Pruning

By default, stale model associations belonging to successfully synchronized providers are removed.

To keep existing routes even when the provider no longer reports them:

```bash
python butterproxy_config_manager.py sync \
  --config /etc/butter/config.yaml \
  --env /opt/eh-stack/config/eh.env \
  --no-prune
```

Synchronization prints a JSON report containing information such as:

```text
providers_synced
provider_counts
models_discovered
routes_added
routes_removed
routes_total
errors
dry_run
config_path
```

---

# Remote Management

The GUI can manage Butter configurations on a remote Linux host using SSH and SFTP.

Default remote paths are:

```text
Butter config:
    /etc/butter/config.yaml

Environment file:
    /opt/eh-stack/config/eh.env
```

These paths can be changed in the GUI.

## Launch With Remote Connection Details

```bash
python butterproxy_config_manager.py gui \
  --host 192.168.1.50 \
  --port 22 \
  --user butter \
  --key ~/.ssh/id_ed25519
```

Custom remote paths can also be supplied:

```bash
python butterproxy_config_manager.py gui \
  --host 192.168.1.50 \
  --user butter \
  --remote-config /etc/butter/config.yaml \
  --remote-env /opt/eh-stack/config/eh.env
```

The connection is still initiated from the GUI so authentication and host-key handling remain explicit.

---

## Remote Model Discovery

Normally:

```text
http://127.0.0.1:11434/v1
```

refers to the machine running the configuration manager.

When **Run discovery on connected SSH host** is enabled, model discovery is executed on the remote machine instead.

This is particularly useful for providers such as Ollama that are listening only on the remote server's loopback interface.

For example:

```text
Laptop
   |
   | SSH
   v
Butter Server
   |
   +--> 127.0.0.1:11434
        Ollama
```

The model endpoint never needs to be exposed to the laptop or the public network.

---

# SSH Profiles

Connection profiles can be saved under:

```text
~/.config/butterproxy-config-manager/ssh-profiles.json
```

Profiles may contain:

- Host.
- Port.
- Username.
- Authentication method.
- Private-key path.
- Host-key preference.
- Sudo preference.
- Butter configuration path.
- Environment file path.
- systemd service name.

They deliberately do **not** contain:

- SSH passwords.
- Private-key passphrases.
- Sudo passwords.

Those fields are cleared when a profile is loaded.

---

# Endpoint Presets

Custom endpoint presets are stored under:

```text
~/.config/butterproxy-config-manager/endpoints.json
```

Only the provider name and URL are stored.

API keys are excluded.

---

# Backups and File Safety

The manager uses temporary files followed by replacement rather than directly overwriting configuration content.

When replacing an existing local configuration or environment file, a backup is normally created using:

```text
<filename>.bak
```

For example:

```text
config.yaml
config.yaml.bak
```

Remote writes also attempt to preserve the existing file before replacement.

When `sudo` is required, the manager uploads a temporary file and installs it into the destination rather than trying to write directly into a protected location.

---

# SSH Host Keys

New SSH host keys are rejected by default.

The GUI provides an explicit:

```text
Trust and save new host key
```

option when connecting to a server for the first time.

Known host information is read from the user's SSH configuration, including:

```text
~/.ssh/known_hosts
```

This prevents unknown hosts from being silently accepted unless the option is deliberately enabled.

---

# systemd Service Management

The remote GUI can restart a Butter systemd service after updating the configuration.

The default service name is:

```text
butter
```

The equivalent remote operation is:

```bash
sudo systemctl restart butter
```

A different service name can be entered in the GUI.

You can also enable:

```text
Restart after save
```

to restart Butter automatically after a successful remote configuration update.

---

# Typical Workflow

For a local Butter installation:

```text
Launch manager
     ↓
Load config.yaml
     ↓
Select/create provider
     ↓
Enter endpoint
     ↓
Fetch /models
     ↓
Select models
     ↓
Apply provider + routes
     ↓
Validate YAML
     ↓
Save config
```

For a remote Butter server:

```text
Launch manager
     ↓
Connect over SSH
     ↓
Load remote config
     ↓
Discover models remotely
     ↓
Select/update providers
     ↓
Validate
     ↓
Save remote config
     ↓
Backup existing file
     ↓
Optionally restart Butter
```

---

# Command Reference

## GUI

```bash
python butterproxy_config_manager.py gui [OPTIONS]
```

Options:

```text
--config PATH
--env PATH
--host HOST
--port PORT
--user USER
--key PATH
--remote-config PATH
--remote-env PATH
```

## Discover

```bash
python butterproxy_config_manager.py discover \
  --base-url URL \
  [--api-key KEY] \
  [--api-key-env VARIABLE]
```

## Sync

```bash
python butterproxy_config_manager.py sync \
  [--config PATH] \
  [--env PATH] \
  [--provider NAME] \
  [--no-prune] \
  [--dry-run]
```

## Summary

```bash
python butterproxy_config_manager.py summary \
  [--config PATH]
```

## Validate

```bash
python butterproxy_config_manager.py validate \
  [--config PATH]
```

---

# Default Paths

| Purpose | Path |
| --- | --- |
| Butter config | `/etc/butter/config.yaml` |
| Butter environment | `/opt/eh-stack/config/eh.env` |
| Manager state | `~/.config/butterproxy-config-manager/` |
| Saved endpoints | `~/.config/butterproxy-config-manager/endpoints.json` |
| Saved SSH profiles | `~/.config/butterproxy-config-manager/ssh-profiles.json` |

The GUI's local defaults are:

```text
config.yaml
.env
```

while the CLI `sync`, `summary`, and `validate` commands default to the system Butter configuration paths.

---

# Error Handling

Expected configuration, discovery, dependency, and transport failures are reported as readable Butter Config Manager errors.

CLI failures return a non-zero exit status, making commands such as `validate` and `sync` suitable for shell scripts and administrative workflows.

Examples of detected problems include:

- Missing Python dependencies.
- Invalid YAML.
- Missing `providers` or `routing.models`.
- Invalid provider names.
- Invalid HTTP/HTTPS base URLs.
- Empty model catalogs.
- API/network failures.
- Invalid remote paths.
- SSH authentication failures.
- Unknown SSH host keys.
- Invalid systemd service names.

---

# Security Notes

A few recommendations when using the manager:

- Prefer environment variables over storing API keys directly in YAML.
- Prefer SSH keys or an SSH agent over password authentication when practical.
- Leave automatic host-key trust disabled after initial setup.
- Review configuration changes before saving.
- Use `--dry-run` before large catalog synchronization changes.
- Keep generated `.bak` files until the updated Butter configuration has been verified.
- Restrict access to environment files containing API credentials.
- Avoid exposing local endpoints such as Ollama publicly when remote SSH discovery can be used instead.

---

# Project Scope

Butterproxy Config Manager intentionally focuses on configuration management.

It provides:

```text
Provider discovery
        +
Model catalog discovery
        +
Butter routing configuration
        +
Local file management
        +
Remote SSH/SFTP management
```

in a single Python script with no separate backend service required.