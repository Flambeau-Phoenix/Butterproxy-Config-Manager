package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path"
	"sort"
	"strconv"
	"strings"
	"time"

	"go.yaml.in/yaml/v4"
	"golang.org/x/crypto/ssh"
)

const butterSSHMaxDocumentBytes = 2 << 20

type butterSSHConnection struct {
	Host          string `json:"host"`
	Port          int    `json:"port"`
	Username      string `json:"username"`
	AuthMethod    string `json:"authMethod"`
	Password      string `json:"password"`
	KeyPath       string `json:"keyPath"`
	KeyPassphrase string `json:"keyPassphrase"`
	UseSudo       bool   `json:"useSudo"`
	SudoPassword  string `json:"sudoPassword"`
	ConfigPath    string `json:"configPath"`
	EnvPath       string `json:"envPath"`
	Service       string `json:"service"`
}

type butterProviderEdit struct {
	Name        string   `json:"name"`
	BaseURL     string   `json:"baseUrl"`
	APIKey      string   `json:"apiKey"`
	KeyEnv      string   `json:"keyEnv"`
	Models      []string `json:"models"`
	MakeDefault bool     `json:"makeDefault"`
}

type butterSSHRequest struct {
	Action     string              `json:"action"`
	Connection butterSSHConnection `json:"connection"`
	Provider   butterProviderEdit  `json:"provider"`
	Path       string              `json:"path"`
	RawYAML    string              `json:"rawYaml"`
}

type butterProviderSummary struct {
	Name         string   `json:"name"`
	BaseURL      string   `json:"base_url"`
	KeyReference string   `json:"key_reference"`
	HasKey       bool     `json:"has_key"`
	IsDefault    bool     `json:"is_default"`
	Models       []string `json:"models"`
	RouteCount   int      `json:"route_count"`
}

type butterConfigSummary struct {
	Status              string                  `json:"status"`
	ConfigPath          string                  `json:"config_path"`
	DefaultProvider     string                  `json:"default_provider"`
	Providers           []butterProviderSummary `json:"providers"`
	ProviderCount       int                     `json:"provider_count"`
	RouteCount          int                     `json:"route_count"`
	RawYAML             string                  `json:"raw_yaml,omitempty"`
	ButterReloadSeconds int                     `json:"butter_reload_seconds"`
}

type butterRemoteEntry struct {
	Name  string `json:"name"`
	Path  string `json:"path"`
	IsDir bool   `json:"isDir"`
	Size  int64  `json:"size"`
}

func handleButterSSH(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusNoContent)
		return
	}
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if ip := remoteIP(r); ip != "127.0.0.1" && ip != "::1" {
		writeButterSSHError(w, http.StatusForbidden, "custom SSH management is available only from the local desktop")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, butterSSHMaxDocumentBytes)
	var request butterSSHRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		writeButterSSHError(w, http.StatusBadRequest, "Invalid request: "+err.Error())
		return
	}
	client, fingerprint, err := connectButterSSH(request.Connection)
	if err != nil {
		writeButterSSHError(w, http.StatusBadGateway, err.Error())
		return
	}
	defer client.Close()

	var result any
	switch request.Action {
	case "test":
		result = map[string]any{
			"status":      "ok",
			"message":     "SSH connection established",
			"fingerprint": fingerprint,
		}
	case "load":
		result, err = loadRemoteButterConfig(client, request.Connection)
	case "list":
		result, err = listRemoteButterDirectory(client, request.Connection, request.Path)
	case "discover":
		result, err = discoverRemoteButterModels(client, request.Connection, request.Provider)
	case "save_provider":
		result, err = saveRemoteButterProvider(client, request.Connection, request.Provider)
	case "delete_provider":
		result, err = deleteRemoteButterProvider(client, request.Connection, request.Provider.Name)
	case "save_raw":
		result, err = saveRemoteButterDocument(client, request.Connection, request.RawYAML)
	case "restart":
		result, err = restartRemoteButter(client, request.Connection)
	default:
		err = fmt.Errorf("unsupported SSH action %q", request.Action)
	}
	if err != nil {
		writeButterSSHError(w, http.StatusBadGateway, err.Error())
		return
	}
	json.NewEncoder(w).Encode(result)
}

func writeButterSSHError(w http.ResponseWriter, status int, message string) {
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(map[string]string{"error": message})
}

func connectButterSSH(connection butterSSHConnection) (*ssh.Client, string, error) {
	host := strings.TrimSpace(connection.Host)
	username := strings.TrimSpace(connection.Username)
	if host == "" || username == "" {
		return nil, "", errors.New("SSH host and username are required")
	}
	port := connection.Port
	if port == 0 {
		port = 22
	}
	if port < 1 || port > 65535 {
		return nil, "", errors.New("SSH port must be between 1 and 65535")
	}

	var auth ssh.AuthMethod
	if connection.AuthMethod == "key" {
		keyPath := strings.TrimSpace(connection.KeyPath)
		if strings.HasPrefix(keyPath, "~/") || strings.HasPrefix(keyPath, "~\\") {
			if home, err := os.UserHomeDir(); err == nil {
				keyPath = pathFromSlashJoin(home, keyPath[2:])
			}
		}
		keyData, err := os.ReadFile(keyPath)
		if err != nil {
			return nil, "", fmt.Errorf("read SSH private key: %w", err)
		}
		var signer ssh.Signer
		if connection.KeyPassphrase != "" {
			signer, err = ssh.ParsePrivateKeyWithPassphrase(keyData, []byte(connection.KeyPassphrase))
		} else {
			signer, err = ssh.ParsePrivateKey(keyData)
		}
		if err != nil {
			return nil, "", fmt.Errorf("parse SSH private key: %w", err)
		}
		auth = ssh.PublicKeys(signer)
	} else {
		if connection.Password == "" {
			return nil, "", errors.New("SSH password is required")
		}
		auth = ssh.Password(connection.Password)
	}

	fingerprint := ""
	config := &ssh.ClientConfig{
		User:    username,
		Auth:    []ssh.AuthMethod{auth},
		Timeout: 15 * time.Second,
		HostKeyCallback: func(_ string, _ net.Addr, key ssh.PublicKey) error {
			fingerprint = ssh.FingerprintSHA256(key)
			return nil
		},
	}
	client, err := ssh.Dial("tcp", net.JoinHostPort(host, strconv.Itoa(port)), config)
	if err != nil {
		return nil, "", fmt.Errorf("SSH connection failed: %w", err)
	}
	return client, fingerprint, nil
}

func pathFromSlashJoin(base, child string) string {
	separator := string(os.PathSeparator)
	return strings.TrimRight(base, "/\\") + separator + strings.ReplaceAll(child, "/", separator)
}

func validateRemotePath(value string) (string, error) {
	clean := strings.TrimSpace(value)
	if !strings.HasPrefix(clean, "/") || strings.ContainsAny(clean, "\x00\r\n") {
		return "", errors.New("remote path must be an absolute Linux path")
	}
	return path.Clean(clean), nil
}

func shellQuote(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "'\"'\"'") + "'"
}

func runButterSSHCommand(client *ssh.Client, connection butterSSHConnection, script string) (string, error) {
	session, err := client.NewSession()
	if err != nil {
		return "", err
	}
	defer session.Close()
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	session.Stdout = &stdout
	session.Stderr = &stderr
	command := "sh -c " + shellQuote(script)
	if connection.UseSudo {
		command = "sudo -S -p '' sh -c " + shellQuote(script)
		sudoPassword := connection.SudoPassword
		if sudoPassword == "" {
			sudoPassword = connection.Password
		}
		session.Stdin = strings.NewReader(sudoPassword + "\n")
	}
	if err := session.Run(command); err != nil {
		detail := strings.TrimSpace(stderr.String())
		if detail == "" {
			detail = err.Error()
		}
		return "", errors.New(detail)
	}
	return stdout.String(), nil
}

func readRemoteButterFile(client *ssh.Client, connection butterSSHConnection, filePath string) (string, error) {
	validated, err := validateRemotePath(filePath)
	if err != nil {
		return "", err
	}
	return runButterSSHCommand(client, connection, "cat -- "+shellQuote(validated))
}

func writeRemoteButterFile(client *ssh.Client, connection butterSSHConnection, filePath, content string) error {
	validated, err := validateRemotePath(filePath)
	if err != nil {
		return err
	}
	if len(content) > butterSSHMaxDocumentBytes {
		return errors.New("remote document exceeds 2 MiB limit")
	}
	encoded := base64.StdEncoding.EncodeToString([]byte(content))
	script := "set -eu; target=" + shellQuote(validated) +
		"; dir=$(dirname -- \"$target\"); tmp=$(mktemp \"$dir/.eh-butter.XXXXXX\")" +
		"; printf %s " + shellQuote(encoded) + " | base64 -d > \"$tmp\"" +
		"; if [ -e \"$target\" ]; then cp -p -- \"$target\" \"$target.before-event-horizon\"" +
		"; chmod --reference=\"$target\" \"$tmp\" 2>/dev/null || chmod 600 \"$tmp\"; fi" +
		"; mv -f -- \"$tmp\" \"$target\""
	_, err = runButterSSHCommand(client, connection, script)
	return err
}

func butterConfigPath(connection butterSSHConnection) string {
	if strings.TrimSpace(connection.ConfigPath) == "" {
		return "/etc/butter/config.yaml"
	}
	return connection.ConfigPath
}

func butterEnvPath(connection butterSSHConnection) string {
	if strings.TrimSpace(connection.EnvPath) == "" {
		return "/opt/eh-stack/config/eh.env"
	}
	return connection.EnvPath
}

func parseButterYAML(raw string) (map[string]any, error) {
	var config map[string]any
	if err := yaml.Unmarshal([]byte(raw), &config); err != nil {
		return nil, fmt.Errorf("invalid Butter YAML: %w", err)
	}
	if config == nil {
		return nil, errors.New("Butter config is empty")
	}
	return config, nil
}

func butterMap(value any) map[string]any {
	if typed, ok := value.(map[string]any); ok {
		return typed
	}
	return nil
}

func butterStringSlice(value any) []string {
	items, ok := value.([]any)
	if !ok {
		if stringsList, ok := value.([]string); ok {
			return stringsList
		}
		return nil
	}
	result := make([]string, 0, len(items))
	for _, item := range items {
		if text, ok := item.(string); ok {
			result = append(result, text)
		}
	}
	return result
}

func butterFirstKey(provider map[string]any) string {
	items, ok := provider["keys"].([]any)
	if !ok || len(items) == 0 {
		return ""
	}
	key := butterMap(items[0])
	if key == nil {
		return ""
	}
	value, _ := key["key"].(string)
	return value
}

func summarizeButterConfig(config map[string]any, raw, configPath string) butterConfigSummary {
	providers := butterMap(config["providers"])
	routing := butterMap(config["routing"])
	routes := butterMap(routing["models"])
	defaultProvider, _ := routing["default_provider"].(string)
	modelsByProvider := map[string][]string{}
	for modelID, rawRoute := range routes {
		route := butterMap(rawRoute)
		for _, provider := range butterStringSlice(route["providers"]) {
			modelsByProvider[provider] = append(modelsByProvider[provider], modelID)
		}
	}
	result := butterConfigSummary{
		Status:              "ok",
		ConfigPath:          configPath,
		DefaultProvider:     defaultProvider,
		ProviderCount:       len(providers),
		RouteCount:          len(routes),
		RawYAML:             raw,
		ButterReloadSeconds: 5,
	}
	for name, rawProvider := range providers {
		provider := butterMap(rawProvider)
		baseURL, _ := provider["base_url"].(string)
		key := butterFirstKey(provider)
		publicKey := ""
		if key == "ollama" || (strings.HasPrefix(key, "${") && strings.HasSuffix(key, "}")) {
			publicKey = key
		} else if key != "" {
			publicKey = "configured"
		}
		models := modelsByProvider[name]
		sort.Strings(models)
		result.Providers = append(result.Providers, butterProviderSummary{
			Name: name, BaseURL: baseURL, KeyReference: publicKey, HasKey: key != "",
			IsDefault: name == defaultProvider, Models: models, RouteCount: len(models),
		})
	}
	sort.Slice(result.Providers, func(i, j int) bool {
		if result.Providers[i].IsDefault != result.Providers[j].IsDefault {
			return result.Providers[i].IsDefault
		}
		return result.Providers[i].Name < result.Providers[j].Name
	})
	return result
}

func loadRemoteButterConfig(client *ssh.Client, connection butterSSHConnection) (butterConfigSummary, error) {
	configPath := butterConfigPath(connection)
	raw, err := readRemoteButterFile(client, connection, configPath)
	if err != nil {
		return butterConfigSummary{}, fmt.Errorf("load remote Butter config: %w", err)
	}
	config, err := parseButterYAML(raw)
	if err != nil {
		return butterConfigSummary{}, err
	}
	return summarizeButterConfig(config, raw, configPath), nil
}

func listRemoteButterDirectory(client *ssh.Client, connection butterSSHConnection, directory string) ([]butterRemoteEntry, error) {
	if strings.TrimSpace(directory) == "" {
		directory = path.Dir(butterConfigPath(connection))
	}
	directory, err := validateRemotePath(directory)
	if err != nil {
		return nil, err
	}
	script := "find " + shellQuote(directory) + " -mindepth 1 -maxdepth 1 -printf '%f\\t%y\\t%s\\n'"
	output, err := runButterSSHCommand(client, connection, script)
	if err != nil {
		return nil, fmt.Errorf("list remote directory: %w", err)
	}
	entries := []butterRemoteEntry{}
	for _, line := range strings.Split(strings.TrimSpace(output), "\n") {
		parts := strings.Split(line, "\t")
		if len(parts) != 3 {
			continue
		}
		size, _ := strconv.ParseInt(parts[2], 10, 64)
		entries = append(entries, butterRemoteEntry{
			Name: parts[0], Path: path.Join(directory, parts[0]), IsDir: parts[1] == "d", Size: size,
		})
	}
	sort.Slice(entries, func(i, j int) bool {
		if entries[i].IsDir != entries[j].IsDir {
			return entries[i].IsDir
		}
		return entries[i].Name < entries[j].Name
	})
	return entries, nil
}

func readButterEnv(raw string) map[string]string {
	result := map[string]string{}
	for _, line := range strings.Split(raw, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") || !strings.Contains(line, "=") {
			continue
		}
		parts := strings.SplitN(line, "=", 2)
		result[strings.TrimSpace(parts[0])] = strings.Trim(strings.TrimSpace(parts[1]), "\"'")
	}
	return result
}

func resolveButterKey(client *ssh.Client, connection butterSSHConnection, providerName string) string {
	raw, err := readRemoteButterFile(client, connection, butterConfigPath(connection))
	if err != nil {
		return ""
	}
	config, err := parseButterYAML(raw)
	if err != nil {
		return ""
	}
	provider := butterMap(butterMap(config["providers"])[providerName])
	key := butterFirstKey(provider)
	if strings.HasPrefix(key, "${") && strings.HasSuffix(key, "}") {
		envRaw, envErr := readRemoteButterFile(client, connection, butterEnvPath(connection))
		if envErr == nil {
			return readButterEnv(envRaw)[strings.TrimSuffix(strings.TrimPrefix(key, "${"), "}")]
		}
	}
	return key
}

func discoverRemoteButterModels(client *ssh.Client, connection butterSSHConnection, provider butterProviderEdit) (map[string]any, error) {
	baseURL := strings.TrimRight(strings.TrimSpace(provider.BaseURL), "/")
	parsed, err := url.Parse(baseURL)
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
		return nil, errors.New("provider base URL must be valid http:// or https:// URL")
	}
	apiKey := strings.TrimSpace(provider.APIKey)
	if apiKey == "" && provider.Name != "" {
		apiKey = resolveButterKey(client, connection, provider.Name)
	}
	transport := &http.Transport{
		DialContext: func(_ context.Context, network, address string) (net.Conn, error) {
			return client.Dial(network, address)
		},
	}
	httpClient := &http.Client{Transport: transport, Timeout: 35 * time.Second}
	defer transport.CloseIdleConnections()
	request, err := http.NewRequest(http.MethodGet, baseURL+"/models", nil)
	if err != nil {
		return nil, err
	}
	request.Header.Set("Accept", "application/json")
	if apiKey != "" && apiKey != "ollama" && apiKey != "none" {
		request.Header.Set("Authorization", "Bearer "+apiKey)
	}
	response, err := httpClient.Do(request)
	if err != nil {
		return nil, fmt.Errorf("provider catalog request failed through SSH: %w", err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, butterSSHMaxDocumentBytes))
	if err != nil {
		return nil, err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return nil, fmt.Errorf("provider catalog returned HTTP %d: %s", response.StatusCode, strings.TrimSpace(string(body)))
	}
	var payload struct {
		Data []struct {
			ID string `json:"id"`
		} `json:"data"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		return nil, fmt.Errorf("invalid provider catalog JSON: %w", err)
	}
	seen := map[string]bool{}
	models := []string{}
	for _, model := range payload.Data {
		id := strings.TrimSpace(model.ID)
		if id != "" && !seen[id] {
			seen[id] = true
			models = append(models, id)
		}
	}
	sort.Strings(models)
	if len(models) == 0 {
		return nil, errors.New("provider catalog returned no model IDs")
	}
	return map[string]any{"status": "ok", "models": models, "model_count": len(models)}, nil
}

func updateButterEnv(raw, key, value string) string {
	lines := strings.Split(strings.ReplaceAll(raw, "\r\n", "\n"), "\n")
	replaced := false
	for index, line := range lines {
		if strings.Contains(line, "=") && strings.TrimSpace(strings.SplitN(line, "=", 2)[0]) == key {
			lines[index] = key + "=" + value
			replaced = true
		}
	}
	if !replaced {
		lines = append(lines, key+"="+value)
	}
	return strings.TrimSpace(strings.Join(lines, "\n")) + "\n"
}

func validateButterProvider(provider butterProviderEdit) (string, []string, error) {
	name := strings.TrimSpace(provider.Name)
	if name == "" || strings.ContainsAny(name, " /\\\r\n\t") {
		return "", nil, errors.New("provider name is required and cannot contain whitespace or slashes")
	}
	base, err := url.Parse(strings.TrimSpace(provider.BaseURL))
	if err != nil || (base.Scheme != "http" && base.Scheme != "https") || base.Host == "" {
		return "", nil, errors.New("provider base URL must be valid http:// or https:// URL")
	}
	seen := map[string]bool{}
	models := []string{}
	for _, value := range provider.Models {
		model := strings.TrimSpace(value)
		if model != "" && !seen[model] {
			seen[model] = true
			models = append(models, model)
		}
	}
	sort.Strings(models)
	if len(models) == 0 {
		return "", nil, errors.New("select at least one model before saving")
	}
	return name, models, nil
}

func saveRemoteButterProvider(client *ssh.Client, connection butterSSHConnection, edit butterProviderEdit) (butterConfigSummary, error) {
	name, models, err := validateButterProvider(edit)
	if err != nil {
		return butterConfigSummary{}, err
	}
	loaded, err := loadRemoteButterConfig(client, connection)
	if err != nil {
		return butterConfigSummary{}, err
	}
	config, _ := parseButterYAML(loaded.RawYAML)
	providers := butterMap(config["providers"])
	if providers == nil {
		providers = map[string]any{}
		config["providers"] = providers
	}
	provider := butterMap(providers[name])
	if provider == nil {
		provider = map[string]any{}
	}
	provider["base_url"] = strings.TrimRight(strings.TrimSpace(edit.BaseURL), "/")
	if strings.TrimSpace(edit.APIKey) != "" {
		envName := strings.TrimSpace(edit.KeyEnv)
		if envName == "" {
			envName = strings.ToUpper(strings.NewReplacer("-", "_", ".", "_").Replace(name)) + "_API_KEY"
		}
		if strings.ContainsAny(envName, " =\r\n\t") {
			return butterConfigSummary{}, errors.New("API key environment variable name is invalid")
		}
		envRaw, _ := readRemoteButterFile(client, connection, butterEnvPath(connection))
		if err := writeRemoteButterFile(client, connection, butterEnvPath(connection), updateButterEnv(envRaw, envName, edit.APIKey)); err != nil {
			return butterConfigSummary{}, fmt.Errorf("save remote environment: %w", err)
		}
		provider["keys"] = []any{map[string]any{"key": "${" + envName + "}", "weight": 1}}
	} else if butterFirstKey(provider) == "" {
		if strings.Contains(provider["base_url"].(string), ":11434") {
			provider["keys"] = []any{map[string]any{"key": "ollama", "weight": 1}}
		} else {
			return butterConfigSummary{}, errors.New("API key is required for a new remote provider")
		}
	}
	providers[name] = provider
	routing := butterMap(config["routing"])
	if routing == nil {
		routing = map[string]any{}
		config["routing"] = routing
	}
	routes := butterMap(routing["models"])
	if routes == nil {
		routes = map[string]any{}
		routing["models"] = routes
	}
	for modelID, rawRoute := range routes {
		route := butterMap(rawRoute)
		current := butterStringSlice(route["providers"])
		remaining := []any{}
		found := false
		for _, providerName := range current {
			if providerName == name {
				found = true
			} else {
				remaining = append(remaining, providerName)
			}
		}
		if found && len(remaining) == 0 {
			delete(routes, modelID)
		} else if found {
			route["providers"] = remaining
		}
	}
	for _, model := range models {
		routes[model] = map[string]any{"providers": []any{name}, "strategy": "priority"}
	}
	if edit.MakeDefault || routing["default_provider"] == nil {
		routing["default_provider"] = name
	}
	rendered, err := yaml.Marshal(config)
	if err != nil {
		return butterConfigSummary{}, err
	}
	if err := writeRemoteButterFile(client, connection, butterConfigPath(connection), string(rendered)); err != nil {
		return butterConfigSummary{}, fmt.Errorf("save remote Butter config: %w", err)
	}
	return loadRemoteButterConfig(client, connection)
}

func deleteRemoteButterProvider(client *ssh.Client, connection butterSSHConnection, name string) (butterConfigSummary, error) {
	name = strings.TrimSpace(name)
	loaded, err := loadRemoteButterConfig(client, connection)
	if err != nil {
		return butterConfigSummary{}, err
	}
	config, _ := parseButterYAML(loaded.RawYAML)
	providers := butterMap(config["providers"])
	if providers == nil || providers[name] == nil {
		return butterConfigSummary{}, errors.New("provider not found")
	}
	routing := butterMap(config["routing"])
	if defaultProvider, _ := routing["default_provider"].(string); defaultProvider == name {
		return butterConfigSummary{}, errors.New("choose another default provider before deleting this provider")
	}
	delete(providers, name)
	routes := butterMap(routing["models"])
	for modelID, rawRoute := range routes {
		route := butterMap(rawRoute)
		remaining := []any{}
		for _, providerName := range butterStringSlice(route["providers"]) {
			if providerName != name {
				remaining = append(remaining, providerName)
			}
		}
		if len(remaining) == 0 {
			delete(routes, modelID)
		} else {
			route["providers"] = remaining
		}
	}
	rendered, err := yaml.Marshal(config)
	if err != nil {
		return butterConfigSummary{}, err
	}
	if err := writeRemoteButterFile(client, connection, butterConfigPath(connection), string(rendered)); err != nil {
		return butterConfigSummary{}, err
	}
	return loadRemoteButterConfig(client, connection)
}

func saveRemoteButterDocument(client *ssh.Client, connection butterSSHConnection, raw string) (butterConfigSummary, error) {
	config, err := parseButterYAML(raw)
	if err != nil {
		return butterConfigSummary{}, err
	}
	if butterMap(config["providers"]) == nil || butterMap(butterMap(config["routing"])["models"]) == nil {
		return butterConfigSummary{}, errors.New("Butter YAML must contain providers and routing.models mappings")
	}
	rendered, err := yaml.Marshal(config)
	if err != nil {
		return butterConfigSummary{}, err
	}
	if err := writeRemoteButterFile(client, connection, butterConfigPath(connection), string(rendered)); err != nil {
		return butterConfigSummary{}, err
	}
	return loadRemoteButterConfig(client, connection)
}

func restartRemoteButter(client *ssh.Client, connection butterSSHConnection) (map[string]string, error) {
	service := strings.TrimSpace(connection.Service)
	if service == "" {
		service = "butter"
	}
	if strings.ContainsAny(service, " /\\\r\n\t;|&$") {
		return nil, errors.New("service name contains invalid characters")
	}
	_, err := runButterSSHCommand(client, butterSSHConnectionWithSudo(connection), "systemctl restart -- "+shellQuote(service))
	if err != nil {
		return nil, fmt.Errorf("restart %s: %w", service, err)
	}
	return map[string]string{"status": "ok", "message": "Restarted " + service}, nil
}

func butterSSHConnectionWithSudo(connection butterSSHConnection) butterSSHConnection {
	connection.UseSudo = true
	return connection
}
