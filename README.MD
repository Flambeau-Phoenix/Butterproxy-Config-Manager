# Butterproxy GUI Config Manager 

A Python-based graphical user interface (GUI) designed to easily fetch available models from OpenAI-compatible API endpoints, update local configuration files, and manage remote headless instances of Butterproxy securely over SSH/SFTP.

## Features

- **Model Discovery:** Instantly queries any OpenAI-compatible `/v1/models` endpoint (such as Ollama, OpenRouter, Groq, DeepSeek, or native OpenAI) and visualizes available models.
- **Search & Filter:** Live search bar to filter down thousands of models down to the exact variants you need.
- **Bulk Selection:** Support for selection inversion, selecting all, or clearing selections for effortless mass addition to config profiles.
- **Integrated SSH & SFTP Browser:** Navigate, download, edit, and upload configuration maps directly on a remote server with a built-in remote file browser.
- **Automated Backups:** Safely renames old remote files to `.yaml.bak` upon update to prevent configuration loss.
- **Service Control:** Option to trigger a systemd service restart (`systemctl restart <service>`) automatically via `sudo` after saving remote settings.
- **Persistent Preset Preserver:** Save your favorite endpoints, custom URLs, and authentication methods locally (`~/.eh-butter-endpoints.json`) to skip re-entering fields.

---

## Prerequisites

Ensure you have Python 3.8+ installed on your system.

### System Dependencies (Linux/macOS)
The graphical layer relies on **Tkinter**. If it isn't bundled with your operating system's python distribution, you can install it using your local package manager:

- **Ubuntu/Debian:** `sudo apt-get install python3-tk`
- **Fedora/RHEL:** `sudo dnf install python3-tkinter`
- **macOS (via Homebrew):** Tkinter comes standard with Homebrew's Python installation.

---

## Installation

1. Clone or download this project's script folder to your machine.
2. Install the necessary Python package dependencies:

```bash
pip install paramiko pyyaml requests
```

*(Alternatively, save these to a `requirements.txt` file and run `pip install -r requirements.txt`)*

---

## Usage

You can launch the interface immediately via the terminal:

```bash
python3 butterproxy_gui.py
```

### CLI Automation Arguments
Pre-populate the GUI fields at launch by declaring parameters directly inside your command execution line:

| Argument | Description | Example |
| :--- | :--- | :--- |
| `--host` | Remote SSH Target Host IP or Domain | `--host 192.168.1.231` |
| `--user` | Remote SSH login username | `--user ehadmin` |
| `--key` | Target path to your SSH private identity key | `--key ~/.ssh/id_ed25519` |
| `--remote-path` | Exact file directory location of the remote config map | `--remote-path /etc/butter/config.yaml` |
| `--fetch-url` | Initial API target provider to search against | `--fetch-url http://localhost:11434/v1` |

**Example Pre-loaded Command:**
```bash
python3 butterproxy_gui.py --host 10.0.0.50 --user admin --remote-path /opt/butter/config.yaml
```

---

## Project Structure & Tabs

1. **Config Manager (Main Tab):** Connect to providers, check/filter fetched model list items, adjust raw structural text inside the editable YAML config preview pane, and save variations.
2. **SSH Remote Tab:** Manage remote access targets. Input credentials (using automated key-file exchange or prompts for active string password authentication). Toggle immediate `systemd` configuration reload rules.
3. **Endpoints Tab:** Quickly review historical presets alongside built-in baseline providers to clean up infrastructure maps dynamically.
