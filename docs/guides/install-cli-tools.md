# Install CLI Tools

You need five command-line tools on your workstation: `oc`, `helm`, `pipx`,
Python 3.11+, and `fips-agents`.

## Python 3.11+

=== "macOS"

    ```bash
    brew install python@3.11
    python3.11 --version
    ```

=== "Linux (RHEL / Fedora)"

    ```bash
    sudo dnf install -y python3.11
    python3.11 --version
    ```

=== "Linux (Debian / Ubuntu)"

    ```bash
    sudo apt-get update
    sudo apt-get install -y python3.11 python3.11-venv
    python3.11 --version
    ```

## pipx

`pipx` installs Python CLIs into isolated environments so they don't pollute
your system Python.

=== "macOS"

    ```bash
    brew install pipx
    pipx ensurepath
    ```

=== "Linux"

    ```bash
    python3.11 -m pip install --user pipx
    python3.11 -m pipx ensurepath
    ```

Restart your shell (or `source ~/.zshrc` / `~/.bashrc`) so the `~/.local/bin`
PATH update takes effect.

## oc (OpenShift CLI)

=== "macOS"

    ```bash
    brew install openshift-cli
    oc version --client
    ```

=== "Linux"

    Download the latest `oc` from the [Red Hat mirror][oc-mirror], extract,
    and put it on your PATH:

    ```bash
    curl -L -o /tmp/oc.tar.gz \
      https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest/openshift-client-linux.tar.gz
    tar -xzf /tmp/oc.tar.gz -C /tmp
    sudo mv /tmp/oc /tmp/kubectl /usr/local/bin/
    oc version --client
    ```

    [oc-mirror]: https://mirror.openshift.com/pub/openshift-v4/clients/ocp/

## helm 3.x

=== "macOS"

    ```bash
    brew install helm
    helm version --short
    ```

=== "Linux"

    ```bash
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
    helm version --short
    ```

## fips-agents

Install via `pipx` so it's globally available:

```bash
pipx install fips-agents-cli
fips-agents --version
```

## Log in to your cluster

```bash
oc login --server=https://api.<cluster-domain>:6443 -u <user>
oc whoami
```

(In the OpenShift web console, click your username → **Copy login command**
to get the exact `oc login --token=...` invocation.)

## Verification

All of these should succeed:

```bash
python3.11 --version       # Python 3.11.x or newer
pipx --version
oc version --client
helm version --short
fips-agents --version
oc whoami                  # logged in
```

## Next

[Registry Setup](registry-setup.md).
