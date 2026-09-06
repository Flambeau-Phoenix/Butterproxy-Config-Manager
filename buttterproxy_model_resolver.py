#!/usr/bin/env python3
"""
Butterproxy GUI Config Manager - Enhanced Edition
A graphical tool to fetch models from OpenAI-compatible endpoints,
update Butterproxy config, and manage remote headless proxies via SSH/SFTP.

Dependencies: paramiko, pyyaml, requests, tkinter
"""

import os
import sys
import json
import argparse
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import requests
import yaml

try:
    import paramiko
    from paramiko import SSHClient, AutoAddPolicy
    from paramiko.sftp_client import SFTPClient
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False

# Default config path
DEFAULT_CONFIG_PATH = "config.yaml"

# Built-in endpoint presets
ENDPOINT_PRESETS = [
    ("Local Ollama", "http://127.0.0.1:11434/v1", ""),
    ("LAN Ollama", "http://192.168.1.231:11434/v1", ""),
    ("OpenRouter", "https://openrouter.ai/api/v1", ""),
    ("OpenAI", "https://api.openai.com/v1", ""),
    ("Groq", "https://api.groq.com/openai/v1", ""),
    ("Together AI", "https://api.together.xyz/v1", ""),
    ("DeepSeek", "https://api.deepseek.com/v1", ""),
]

# Common remote config paths for known stacks
REMOTE_CONFIG_PRESETS = [
    ("Butterproxy", "/etc/butter/config.yaml"),
    ("Ollama Modelfile", "/usr/share/ollama/.ollama/models/Modelfile"),
    ("EH Gateway", "/etc/butter/config.yaml"),
    ("Custom Path", ""),
]


class SSHManager:
    """Handles SSH/SFTP operations for remote config management."""

    def __init__(self):
        self.ssh_client = None
        self.sftp_client = None
        self.connected = False

    def connect(self, host, port=22, username="", password=None, key_path=None):
        """Establish SSH connection."""
        if not PARAMIKO_AVAILABLE:
            raise RuntimeError("paramiko not installed. Run: pip install paramiko")

        self.disconnect()
        self.ssh_client = SSHClient()
        self.ssh_client.set_missing_host_key_policy(AutoAddPolicy())

        try:
            if key_path:
                key_path = os.path.expanduser(key_path)
                if not os.path.exists(key_path):
                    raise FileNotFoundError(f"Key file not found: {key_path}")
                self.ssh_client.connect(
                    hostname=host,
                    port=port,
                    username=username,
                    key_filename=key_path,
                    timeout=15,
                    allow_agent=True,
                    look_for_keys=False,
                )
            else:
                self.ssh_client.connect(
                    hostname=host,
                    port=port,
                    username=username,
                    password=password,
                    timeout=15,
                    allow_agent=True,
                    look_for_keys=False,
                )

            self.sftp_client = self.ssh_client.open_sftp()
            self.connected = True
            return True
        except Exception:
            self.connected = False
            raise

    def disconnect(self):
        """Close SSH/SFTP connections."""
        if self.sftp_client:
            try:
                self.sftp_client.close()
            except Exception:
                pass
            self.sftp_client = None
        if self.ssh_client:
            try:
                self.ssh_client.close()
            except Exception:
                pass
            self.ssh_client = None
        self.connected = False

    def read_remote_file(self, remote_path):
        """Read a remote file via SFTP."""
        if not self.sftp_client:
            raise RuntimeError("SFTP not connected")
        with self.sftp_client.file(remote_path, 'r') as f:
            content = f.read().decode('utf-8')
        return content

    def write_remote_file(self, remote_path, content, backup=True):
        """Write content to remote file with optional backup."""
        if not self.sftp_client:
            raise RuntimeError("SFTP not connected")

        if backup:
            try:
                self.sftp_client.stat(remote_path)
                backup_path = remote_path + ".bak"
                self.sftp_client.rename(remote_path, backup_path)
            except IOError:
                pass

        tmp_path = remote_path + ".tmp"
        with self.sftp_client.file(tmp_path, 'w') as f:
            f.write(content)
        self.sftp_client.rename(tmp_path, remote_path)

    def execute_command(self, command, use_sudo=False):
        """Execute a remote command via SSH."""
        if not self.ssh_client:
            raise RuntimeError("SSH not connected")

        if use_sudo:
            command = f"sudo -n {command}"

        stdin, stdout, stderr = self.ssh_client.exec_command(command, timeout=60)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8').strip()
        err = stderr.read().decode('utf-8').strip()
        return exit_code, out, err

    def list_remote_dir(self, path):
        """List contents of a remote directory."""
        if not self.sftp_client:
            raise RuntimeError("SFTP not connected")
        try:
            entries = []
            for entry in self.sftp_client.listdir_attr(path):
                entries.append({
                    'name': entry.filename,
                    'is_dir': entry.st_mode and (entry.st_mode & 0o040000) != 0,
                    'size': entry.st_size,
                })
            return entries
        except Exception as e:
            raise RuntimeError(f"Cannot list directory {path}: {e}")


class RemoteBrowserDialog(tk.Toplevel):
    """Simple remote file browser dialog."""

    def __init__(self, parent, ssh_manager, start_path="/"):
        super().__init__(parent)
        self.title("Remote File Browser")
        self.geometry("700x500")
        self.transient(parent)
        self.grab_set()

        self.ssh = ssh_manager
        self.selected_path = None
        self.current_path = start_path

        frame = ttk.Frame(self, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        path_frame = ttk.Frame(frame)
        path_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(path_frame, text="Path:").pack(side=tk.LEFT)
        self.path_var = tk.StringVar(value=start_path)
        ttk.Entry(path_frame, textvariable=self.path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(path_frame, text="Go", command=self.navigate).pack(side=tk.LEFT)

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(list_frame, columns=('type', 'size'), show='tree headings')
        self.tree.heading('#0', text='Name')
        self.tree.heading('type', text='Type')
        self.tree.heading('size', text='Size')
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scrollbar.set)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn_frame, text="Up", command=self.go_up).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Select File", command=self.select_file).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(0, 5))

        self.tree.bind('<Double-1>', self.on_double_click)
        self.navigate()

    def navigate(self):
        path = self.path_var.get()
        try:
            entries = self.ssh.list_remote_dir(path)
            self.tree.delete(*self.tree.get_children())
            for e in sorted(entries, key=lambda x: (not x['is_dir'], x['name'])):
                icon = "📁" if e['is_dir'] else "📄"
                self.tree.insert('', 'end', text=f"{icon} {e['name']}",
                                 values=('Dir' if e['is_dir'] else 'File', e['size']))
            self.current_path = path
        except Exception as e:
            messagebox.showerror("Error", f"Cannot list directory:\n{e}", parent=self)

    def go_up(self):
        parts = self.current_path.rstrip('/').split('/')
        if len(parts) > 1:
            parts.pop()
            new_path = '/'.join(parts) or '/'
            self.path_var.set(new_path + '/')
            self.navigate()

    def on_double_click(self, event):
        sel = self.tree.selection()
        if sel:
            item = self.tree.item(sel[0])
            name = item['text'].split(' ', 1)[-1]
            if item['values'][0] == 'Dir':
                new_path = os.path.join(self.current_path, name).replace('\\', '/').replace('//', '/')
                self.path_var.set(new_path + '/')
                self.navigate()
            else:
                self.path_var.set(os.path.join(self.current_path, name).replace('\\', '/').replace('//', '/'))
                self.select_file()

    def select_file(self):
        self.selected_path = self.path_var.get()
        self.destroy()


class ButterproxyGUI:
    def __init__(self, root, cli_args=None):
        self.root = root
        self.root.title("Butterproxy Config Manager - Remote Enhanced")
        self.root.geometry("900x820")
        self.root.resizable(True, True)

        self.cli_args = cli_args or {}

        self.providers = {}
        self.current_provider = ""
        self.config_path = DEFAULT_CONFIG_PATH
        self.remote_mode = tk.BooleanVar(value=False)
        self.saved_endpoints = self.load_saved_endpoints()

        self.ssh = SSHManager()
        self._current_provider_info = None
        self._fetched_models = []

        self.setup_ui()
        self.apply_cli_args()
        self.load_existing_config()

    def setup_ui(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        main_tab = ttk.Frame(notebook)
        notebook.add(main_tab, text="Config Manager")
        self.setup_main_tab(main_tab)

        remote_tab = ttk.Frame(notebook)
        notebook.add(remote_tab, text="SSH Remote")
        self.setup_remote_tab(remote_tab)

        presets_tab = ttk.Frame(notebook)
        notebook.add(presets_tab, text="Endpoints")
        self.setup_presets_tab(presets_tab)

        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status_var,
                               relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def setup_main_tab(self, parent):
        main_frame = ttk.Frame(parent, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        endpoint_frame = ttk.LabelFrame(main_frame, text="Endpoint Configuration", padding="10")
        endpoint_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(endpoint_frame, text="Provider Name:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.provider_name_var = tk.StringVar(value="openai")
        provider_combo = ttk.Combobox(endpoint_frame, textvariable=self.provider_name_var, width=22)
        provider_combo['values'] = [p[0] for p in ENDPOINT_PRESETS] + list(self.saved_endpoints.keys())
        provider_combo.grid(row=0, column=1, sticky=tk.W, pady=2, padx=(5, 20))
        provider_combo.bind('<<ComboboxSelected>>', self.on_preset_select)

        ttk.Label(endpoint_frame, text="API Base URL:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.api_base_var = tk.StringVar(value="https://api.openai.com/v1")
        ttk.Entry(endpoint_frame, textvariable=self.api_base_var, width=60).grid(
            row=1, column=1, columnspan=2, sticky=tk.W, pady=2, padx=5)

        ttk.Label(endpoint_frame, text="API Key (optional):").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.api_key_var = tk.StringVar()
        ttk.Entry(endpoint_frame, textvariable=self.api_key_var, width=60, show="*").grid(
            row=2, column=1, columnspan=2, sticky=tk.W, pady=2, padx=5)

        save_preset_btn = ttk.Button(endpoint_frame, text="💾 Save Preset",
                                     command=self.save_current_as_preset)
        save_preset_btn.grid(row=3, column=0, pady=5)

        self.fetch_btn = ttk.Button(endpoint_frame, text="🔍 Fetch Models", command=self.fetch_models)
        self.fetch_btn.grid(row=3, column=1, columnspan=2, pady=5, sticky=tk.W)

        models_frame = ttk.LabelFrame(main_frame, text="Available Models (Searchable)", padding="10")
        models_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        search_frame = ttk.Frame(models_frame)
        search_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(search_frame, text="🔍 Filter:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add('write', self.filter_models)
        ttk.Entry(search_frame, textvariable=self.search_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        btn_frame = ttk.Frame(models_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(btn_frame, text="Select All", command=self.select_all_models).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Deselect All", command=self.deselect_all_models).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Invert Selection", command=self.invert_selection).pack(side=tk.LEFT)

        list_frame = ttk.Frame(models_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.models_tree = ttk.Treeview(list_frame, columns=('id',), show='tree headings', selectmode='extended')
        self.models_tree.heading('#0', text='Model ID')
        self.models_tree.column('#0', width=400)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.models_tree.yview)
        self.models_tree.configure(yscrollcommand=scrollbar.set)
        self.models_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.model_count_var = tk.StringVar(value="0 models loaded")
        ttk.Label(models_frame, textvariable=self.model_count_var, foreground="gray").pack(anchor=tk.W, pady=(5, 0))

        actions_frame = ttk.LabelFrame(main_frame, text="Actions", padding="10")
        actions_frame.pack(fill=tk.X)

        button_row = ttk.Frame(actions_frame)
        button_row.pack(fill=tk.X)

        self.add_btn = ttk.Button(button_row, text="➕ Add Selected to Config", command=self.add_selected_models)
        self.add_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.save_btn = ttk.Button(button_row, text="💾 Save Config File", command=self.save_config)
        self.save_btn.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(button_row, text="📂 Load Config", command=self.load_config_file).pack(side=tk.LEFT)

        preview_frame = ttk.LabelFrame(main_frame, text="Config Preview (YAML format - editable)", padding="10")
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.preview_text = scrolledtext.ScrolledText(preview_frame, height=10, font=("Courier New", 9))
        self.preview_text.pack(fill=tk.BOTH, expand=True)

    def setup_remote_tab(self, parent):
        frame = ttk.Frame(parent, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        conn_frame = ttk.LabelFrame(frame, text="SSH/SFTP Connection Profile", padding="10")
        conn_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(conn_frame, text="Host/IP:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.remote_host_var = tk.StringVar(value="192.168.1.231")
        ttk.Entry(conn_frame, textvariable=self.remote_host_var, width=30).grid(row=0, column=1, sticky=tk.W, pady=2, padx=5)

        ttk.Label(conn_frame, text="Port:").grid(row=0, column=2, sticky=tk.W, pady=2)
        self.remote_port_var = tk.IntVar(value=22)
        ttk.Entry(conn_frame, textvariable=self.remote_port_var, width=8).grid(row=0, column=3, sticky=tk.W, pady=2, padx=5)

        ttk.Label(conn_frame, text="Username:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.remote_user_var = tk.StringVar(value="ehadmin")
        ttk.Entry(conn_frame, textvariable=self.remote_user_var, width=30).grid(row=1, column=1, sticky=tk.W, pady=2, padx=5)

        ttk.Label(conn_frame, text="Auth Method:").grid(row=1, column=2, sticky=tk.W, pady=2)
        self.auth_method_var = tk.StringVar(value="key")
        auth_combo = ttk.Combobox(conn_frame, textvariable=self.auth_method_var, width=10, state='readonly')
        auth_combo['values'] = ['key', 'password']
        auth_combo.grid(row=1, column=3, sticky=tk.W, pady=2, padx=5)

        ttk.Label(conn_frame, text="Key Path / Password:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.remote_key_var = tk.StringVar(value="~/.ssh/id_ed25519")
        key_entry = ttk.Entry(conn_frame, textvariable=self.remote_key_var, width=40)
        key_entry.grid(row=2, column=1, sticky=tk.W, pady=2, padx=5)
        ttk.Button(conn_frame, text="Browse", command=self.browse_key_file).grid(row=2, column=2, pady=2)

        btn_frame = ttk.Frame(conn_frame)
        btn_frame.grid(row=3, column=0, columnspan=4, pady=10)
        self.connect_btn = ttk.Button(btn_frame, text="🔌 Connect", command=self.connect_remote)
        self.connect_btn.pack(side=tk.LEFT, padx=(0, 5))
        self.disconnect_btn = ttk.Button(btn_frame, text="❌ Disconnect", command=self.disconnect_remote, state=tk.DISABLED)
        self.disconnect_btn.pack(side=tk.LEFT)
        self.remote_status_var = tk.StringVar(value="Not connected")
        ttk.Label(conn_frame, textvariable=self.remote_status_var, foreground="gray").grid(row=4, column=0, columnspan=4, sticky=tk.W)

        path_frame = ttk.LabelFrame(frame, text="Remote Config Path", padding="10")
        path_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(path_frame, text="Remote Path:").grid(row=0, column=0, sticky=tk.W)
        self.remote_path_var = tk.StringVar(value="/opt/eh-stack/config/config.yaml")
        path_combo = ttk.Combobox(path_frame, textvariable=self.remote_path_var, width=50)
        path_combo['values'] = [p[1] for p in REMOTE_CONFIG_PRESETS if p[1]]
        path_combo.grid(row=0, column=1, sticky=tk.W, padx=5)
        ttk.Button(path_frame, text="📂 Browse Remote", command=self.browse_remote).grid(row=0, column=2)

        actions_frame = ttk.LabelFrame(frame, text="Remote Actions", padding="10")
        actions_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(actions_frame, text="📥 Load Remote Config", command=self.load_remote_config).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(actions_frame, text="📤 Save Remote Config", command=self.save_remote_config).pack(side=tk.LEFT, padx=(0, 5))

        self.restart_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(actions_frame, text="Restart Service After Save", variable=self.restart_var).pack(side=tk.LEFT, padx=(10, 5))

        ttk.Label(actions_frame, text="Service:").pack(side=tk.LEFT)
        self.service_name_var = tk.StringVar(value="butterproxy")
        ttk.Entry(actions_frame, textvariable=self.service_name_var, width=20).pack(side=tk.LEFT, padx=5)
        ttk.Button(actions_frame, text="🔄 Restart Now", command=self.restart_service).pack(side=tk.LEFT, padx=(5, 0))

    def setup_presets_tab(self, parent):
        frame = ttk.Frame(parent, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        builtin_frame = ttk.LabelFrame(frame, text="Built-in Endpoint Presets", padding="10")
        builtin_frame.pack(fill=tk.X, pady=(0, 10))

        cols = ('name', 'url')
        self.preset_tree = ttk.Treeview(builtin_frame, columns=cols, show='headings', height=8)
        self.preset_tree.heading('name', text='Name')
        self.preset_tree.heading('url', text='URL')
        self.preset_tree.column('name', width=150)
        self.preset_tree.column('url', width=400)
        self.preset_tree.pack(fill=tk.X)
        for name, url, _ in ENDPOINT_PRESETS:
            self.preset_tree.insert('', 'end', values=(name, url))

        self.preset_tree.bind('<Double-1>', self.load_preset_to_main)

        saved_frame = ttk.LabelFrame(frame, text="Your Saved Endpoints", padding="10")
        saved_frame.pack(fill=tk.BOTH, expand=True)

        cols2 = ('name', 'url', 'key')
        self.saved_tree = ttk.Treeview(saved_frame, columns=cols2, show='headings', height=8)
        self.saved_tree.heading('name', text='Name')
        self.saved_tree.heading('url', text='URL')
        self.saved_tree.heading('key', text='Has Key')
        self.saved_tree.column('name', width=150)
        self.saved_tree.column('url', width=350)
        self.saved_tree.column('key', width=80)
        self.saved_tree.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        btn_frame = ttk.Frame(saved_frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Load Selected", command=self.load_saved_preset).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Delete Selected", command=self.delete_saved_preset).pack(side=tk.LEFT)

        self.refresh_saved_tree()

    # --- Endpoint Preset Methods ---

    def load_saved_endpoints(self):
        """Load saved endpoint presets from a JSON file."""
        path = os.path.expanduser("~/.eh-butter-endpoints.json")
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_saved_endpoints(self):
        """Save endpoint presets to disk."""
        path = os.path.expanduser("~/.eh-butter-endpoints.json")
        try:
            with open(path, 'w') as f:
                json.dump(self.saved_endpoints, f, indent=2)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save presets: {e}")

    def save_current_as_preset(self):
        """Save current endpoint config as a preset."""
        name = self.provider_name_var.get().strip()
        url = self.api_base_var.get().strip()
        key = self.api_key_var.get().strip()
        if not name or not url:
            messagebox.showwarning("Warning", "Provider name and URL required")
            return
        self.saved_endpoints[name] = {'url': url, 'key': key}
        self.save_saved_endpoints()
        self.refresh_saved_tree()
        self.status_var.set(f"✅ Saved preset: {name}")

    def refresh_saved_tree(self):
        """Refresh the saved presets tree."""
        self.saved_tree.delete(*self.saved_tree.get_children())
        for name, data in self.saved_endpoints.items():
            has_key = "Yes" if data.get('key') else "No"
            self.saved_tree.insert('', 'end', values=(name, data.get('url', ''), has_key))

    def load_saved_preset(self):
        """Load a selected saved preset into the main tab."""
        sel = self.saved_tree.selection()
        if not sel:
            return
        values = self.saved_tree.item(sel[0])['values']
        name = values[0]
        if name in self.saved_endpoints:
            data = self.saved_endpoints[name]
            self.provider_name_var.set(name)
            self.api_base_var.set(data.get('url', ''))
            self.api_key_var.set(data.get('key', ''))
            self.status_var.set(f"Loaded preset: {name}")

    def delete_saved_preset(self):
        """Delete a saved preset."""
        sel = self.saved_tree.selection()
        if not sel:
            return
        name = self.saved_tree.item(sel[0])['values'][0]
        if name in self.saved_endpoints:
            del self.saved_endpoints[name]
            self.save_saved_endpoints()
            self.refresh_saved_tree()
            self.status_var.set(f"Deleted preset: {name}")

    def load_preset_to_main(self, event=None):
        """Load a built-in preset to the main tab fields."""
        sel = self.preset_tree.selection()
        if not sel:
            return
        values = self.preset_tree.item(sel[0])['values']
        name = values[0]
        url = values[1]
        for pname, purl, pkey in ENDPOINT_PRESETS:
            if pname == name:
                self.provider_name_var.set(name)
                self.api_base_var.set(url)
                self.api_key_var.set(pkey)
                self.status_var.set(f"Loaded built-in preset: {name}")
                break

    def on_preset_select(self, event=None):
        """Handle selection from provider name combobox."""
        name = self.provider_name_var.get()
        for pname, purl, pkey in ENDPOINT_PRESETS:
            if pname == name:
                self.api_base_var.set(purl)
                if pkey:
                    self.api_key_var.set(pkey)
                return
        if name in self.saved_endpoints:
            data = self.saved_endpoints[name]
            self.api_base_var.set(data.get('url', ''))
            self.api_key_var.set(data.get('key', ''))

    # --- Model Selection & Filtering Methods ---

    def select_all_models(self):
        """Select all visible items in the models tree."""
        children = self.models_tree.get_children()
        if children:
            self.models_tree.selection_set(children)

    def deselect_all_models(self):
        """Clear selection in the models tree."""
        self.models_tree.selection_set([])

    def invert_selection(self):
        """Invert the current selection in the models tree."""
        all_items = set(self.models_tree.get_children())
        selected = set(self.models_tree.selection())
        new_selection = all_items - selected
        self.models_tree.selection_set(list(new_selection))

    def filter_models(self, *args):
        """Filter the models tree based on the search query."""
        search = self.search_var.get().strip().lower()

        if not hasattr(self, '_fetched_models') or not self._fetched_models:
            return

        self.models_tree.delete(*self.models_tree.get_children())

        for model in sorted(self._fetched_models):
            if search == "" or search in model.lower():
                self.models_tree.insert('', 'end', text=model, values=(model,))

    # --- SSH/SFTP Methods ---

    def browse_key_file(self):
        """Browse for a private key file."""
        path = filedialog.askopenfilename(
            title="Select SSH Private Key",
            filetypes=[("All files", "*.*")],
            initialdir=os.path.expanduser("~/.ssh")
        )
        if path:
            self.remote_key_var.set(path)

    def connect_remote(self):
        """Connect to remote host via SSH."""
        host = self.remote_host_var.get().strip()
        port = self.remote_port_var.get()
        user = self.remote_user_var.get().strip()
        method = self.auth_method_var.get()

        if not host or not user:
            messagebox.showerror("Error", "Host and Username required")
            return

        try:
            if method == "key":
                key_path = self.remote_key_var.get().strip()
                self.ssh.connect(host, port, user, key_path=key_path)
            else:
                import tkinter.simpledialog as sd
                pwd = sd.askstring("Password", "Enter SSH password:", show='*', parent=self.root)
                if not pwd:
                    return
                self.ssh.connect(host, port, user, password=pwd)

            self.connect_btn.config(state=tk.DISABLED)
            self.disconnect_btn.config(state=tk.NORMAL)
            self.remote_status_var.set(f"✅ Connected to {user}@{host}:{port}")
            self.status_var.set(f"SSH connected to {host}")
        except Exception as e:
            messagebox.showerror("Connection Error", f"Failed to connect:\n{e}")
            self.remote_status_var.set(f"❌ Connection failed: {e}")

    def disconnect_remote(self):
        """Disconnect from remote."""
        self.ssh.disconnect()
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)
        self.remote_status_var.set("Disconnected")
        self.status_var.set("SSH disconnected")

    def browse_remote(self):
        """Open remote file browser."""
        if not self.ssh.connected:
            messagebox.showwarning("Warning", "Connect to remote first")
            return
        start = self.remote_path_var.get() or "/"
        browser = RemoteBrowserDialog(self.root, self.ssh, os.path.dirname(start) or '/')
        self.root.wait_window(browser)
        if browser.selected_path:
            self.remote_path_var.set(browser.selected_path)

    def load_remote_config(self):
        """Load config from remote host."""
        if not self.ssh.connected:
            messagebox.showwarning("Warning", "Not connected to remote")
            return
        path = self.remote_path_var.get().strip()
        if not path:
            messagebox.showwarning("Warning", "Enter a remote path")
            return
        try:
            content = self.ssh.read_remote_file(path)
            config = yaml.safe_load(content) or {}
            if 'providers' in config:
                self.providers = config['providers']
                self.update_preview()
                self.status_var.set(f"✅ Loaded remote config from {path}")
                messagebox.showinfo("Success", f"Loaded config from:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load remote config:\n{e}")

    def save_remote_config(self):
        """Save config to remote host with backup."""
        if not self.ssh.connected:
            messagebox.showwarning("Warning", "Not connected to remote")
            return
        path = self.remote_path_var.get().strip()
        if not path:
            messagebox.showwarning("Warning", "Enter a remote path")
            return
        if not self.providers:
            messagebox.showwarning("Warning", "No providers configured")
            return

        try:
            content = self.preview_text.get(1.0, tk.END).strip()
            yaml.safe_load(content)

            self.ssh.write_remote_file(path, content + "\n", backup=True)
            self.status_var.set(f"✅ Saved remote config to {path}")

            if self.restart_var.get() and self.service_name_var.get():
                self.restart_service()

            messagebox.showinfo("Success", f"Config saved to:\n{path}")
        except yaml.YAMLError as e:
            messagebox.showerror("YAML Error", f"Invalid YAML:\n{e}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save remote config:\n{e}")

    def restart_service(self):
        """Restart a remote systemd service."""
        if not self.ssh.connected:
            messagebox.showwarning("Warning", "Not connected to remote")
            return
        service = self.service_name_var.get().strip()
        if not service:
            messagebox.showwarning("Warning", "Enter a service name")
            return

        try:
            cmd = f"systemctl restart {service}"
            exit_code, out, err = self.ssh.execute_command(cmd, use_sudo=True)
            if exit_code == 0:
                self.status_var.set(f"✅ Restarted {service}")
                messagebox.showinfo("Success", f"Service '{service}' restarted")
            else:
                self.status_var.set(f"❌ Restart failed: {err}")
                messagebox.showerror("Error", f"Failed to restart {service}:\n{err}")
        except Exception as e:
            messagebox.showerror("Error", f"Restart command failed:\n{e}")

    # --- Main Config Methods ---

    def apply_cli_args(self):
        """Apply CLI arguments to the UI."""
        if self.cli_args.get('host'):
            self.remote_host_var.set(self.cli_args['host'])
            self.remote_mode.set(True)
        if self.cli_args.get('user'):
            self.remote_user_var.set(self.cli_args['user'])
        if self.cli_args.get('key'):
            self.remote_key_var.set(self.cli_args['key'])
        if self.cli_args.get('remote_path'):
            self.remote_path_var.set(self.cli_args['remote_path'])
        if self.cli_args.get('fetch_url'):
            self.api_base_var.set(self.cli_args['fetch_url'])

    def load_existing_config(self):
        """Load existing local config if it exists."""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    config = yaml.safe_load(f) or {}
                    if 'providers' in config:
                        self.providers = config['providers']
                        self.update_preview()
        except Exception:
            pass

    def load_config_file(self):
        """Load a local config file via file dialog."""
        file_path = filedialog.askopenfilename(
            title="Select Butterproxy Config File",
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")]
        )
        if file_path:
            self.config_path = file_path
            try:
                with open(file_path, 'r') as f:
                    config = yaml.safe_load(f) or {}
                    if 'providers' in config:
                        self.providers = config['providers']
                        self.update_preview()
                        self.status_var.set(f"Loaded config from {file_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load config:\n{e}")

    def fetch_models(self):
        """Fetch models from the specified endpoint."""
        api_base = self.api_base_var.get().strip()
        api_key = self.api_key_var.get().strip()
        provider_name = self.provider_name_var.get().strip()

        if not api_base:
            messagebox.showerror("Error", "Please enter an API Base URL")
            return
        if not provider_name:
            messagebox.showerror("Error", "Please enter a Provider Name")
            return

        is_local = any(host in api_base for host in ['127.0.0.1', 'localhost', '192.168.', '10.', '172.'])
        if not api_key and not is_local:
            messagebox.showerror("Error", "API Key required for remote endpoints")
            return

        self.current_provider = provider_name
        self.fetch_btn.config(state=tk.DISABLED, text="⏳ Fetching...")
        self.status_var.set("Fetching models...")
        self.root.update()

        try:
            url = f"{api_base.rstrip('/')}/models"
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            data = response.json()
            models = [model['id'] for model in data.get('data', []) if 'id' in model]

            seen = set()
            unique_models = []
            for m in models:
                if m not in seen:
                    seen.add(m)
                    unique_models.append(m)

            self._fetched_models = unique_models
            self.update_model_list(unique_models)

            self._current_provider_info = {
                'name': provider_name,
                'base_url': api_base,
                'api_key': api_key
            }

            self.status_var.set(f"✅ Fetched {len(unique_models)} models from {provider_name}")

        except requests.exceptions.RequestException as e:
            messagebox.showerror("Error", f"Failed to fetch models:\n{e}")
            self.status_var.set("❌ Fetch failed")
        except Exception as e:
            messagebox.showerror("Error", f"Unexpected error:\n{e}")
            self.status_var.set("❌ Error")
        finally:
            self.fetch_btn.config(state=tk.NORMAL, text="🔍 Fetch Models")

    def update_model_list(self, models):
        """Update the treeview with fetched models."""
        self.models_tree.delete(*self.models_tree.get_children())
        for model in sorted(models):
            self.models_tree.insert('', 'end', text=model, values=(model,))
        self.model_count_var.set(f"{len(models)} models loaded")

    def add_selected_models(self):
        """Add selected models to the provider configuration."""
        selected = self.models_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select at least one model")
            return

        if not self._current_provider_info:
            messagebox.showerror("Error", "Please fetch models from an endpoint first")
            return

        provider_name = self._current_provider_info['name']
        models = [self.models_tree.item(item)['text'] for item in selected]

        if provider_name not in self.providers:
            self.providers[provider_name] = {}

        self.providers[provider_name]['base_url'] = self._current_provider_info['base_url']

        if self._current_provider_info['api_key']:
            self.providers[provider_name]['api_key'] = f"${{{provider_name.upper()}_API_KEY}}"
        else:
            self.providers[provider_name]['api_key'] = ""

        if 'models' not in self.providers[provider_name]:
            self.providers[provider_name]['models'] = []

        existing_models = set(self.providers[provider_name]['models'])
        new_models = [m for m in models if m not in existing_models]
        self.providers[provider_name]['models'].extend(new_models)
        self.providers[provider_name]['models'].sort()

        self.update_preview()
        self.status_var.set(f"✅ Added {len(new_models)} models to provider '{provider_name}'")
        messagebox.showinfo("Success", f"Added {len(new_models)} models to provider '{provider_name}'")

    def update_preview(self):
        """Update the preview text area with current config."""
        try:
            config = {'providers': self.providers} if self.providers else {}

            if not config:
                config = {
                    'providers': {},
                    'routes': [],
                    'defaults': {
                        'timeout': 60,
                        'max_retries': 3
                    }
                }

            yaml_str = yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)
            self.preview_text.delete(1.0, tk.END)
            self.preview_text.insert(1.0, yaml_str)
        except Exception as e:
            self.preview_text.delete(1.0, tk.END)
            self.preview_text.insert(1.0, f"# Error generating preview: {e}")

    def save_config(self):
        """Save the current config to a local file."""
        if not self.providers:
            messagebox.showwarning("Warning", "No providers configured to save")
            return

        try:
            content = self.preview_text.get(1.0, tk.END).strip()
            yaml.safe_load(content)

            file_path = filedialog.asksaveasfilename(
                title="Save Config File",
                defaultextension=".yaml",
                filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")],
                initialfile=os.path.basename(self.config_path)
            )

            if not file_path:
                return

            with open(file_path, 'w') as f:
                f.write(content + "\n")

            self.config_path = file_path
            self.status_var.set(f"✅ Config saved to {file_path}")
            messagebox.showinfo("Success", f"Config saved to:\n{file_path}")

        except yaml.YAMLError as e:
            messagebox.showerror("YAML Error", f"Invalid YAML in preview:\n{e}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save config:\n{e}")

    def on_closing(self):
        """Handle window close."""
        if self.ssh.connected:
            self.ssh.disconnect()
        if self.providers:
            if messagebox.askyesno("Save Changes?", "Do you want to save your changes before exiting?"):
                self.save_config()
        self.root.destroy()


def parse_args():
    """Parse command line arguments for direct UI integration."""
    parser = argparse.ArgumentParser(description="Butterproxy Config Manager - Remote Enhanced")
    parser.add_argument("--host", help="Remote SSH host/IP")
    parser.add_argument("--user", help="Remote SSH username")
    parser.add_argument("--key", help="Path to SSH private key")
    parser.add_argument("--remote-path", dest="remote_path", help="Remote config file path")
    parser.add_argument("--fetch-url", dest="fetch_url", help="API base URL to pre-fill")
    return parser.parse_known_args()[0]


def main():
    args = parse_args()
    cli_args = {
        'host': args.host,
        'user': args.user,
        'key': args.key,
        'remote_path': args.remote_path,
        'fetch_url': args.fetch_url,
    }

    if not PARAMIKO_AVAILABLE:
        print("Warning: paramiko not installed. SSH features will be disabled.")
        print("Install with: pip install paramiko")

    root = tk.Tk()
    app = ButterproxyGUI(root, cli_args)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()