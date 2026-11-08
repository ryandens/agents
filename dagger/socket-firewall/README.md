# Socket Firewall

An independent Python Dagger module that protects package-manager downloads inside
a caller's container. It can be moved, with its generated `sdk` and `clients`
directories, to a Daggerverse repository without an application dependency.

## API

- `install(container, binary=None)` returns the caller's container with `sfw` added.
- `run(container, args, binary=None)` executes an argument vector through `sfw`
  and returns the resulting container. Any nonzero exit fails the execution.

The default release supports glibc Linux on amd64 and arm64. Downloads use GitHub
release checksums through Dagger's HTTP checksum enforcement. The container supplies
CA certificates and runtime libraries. A custom binary is an explicit trusted
override, useful for a separately verified release or deterministic test fixture.

Call it through a generated module client:

```python
from dagger_clients.socket_firewall import socket_firewall

installed = socket_firewall().run(
    python_container,
    ["uv", "sync", "--locked", "--dev", "--package", "agents"],
)
```

Socket is a package-manager wrapper, not a general egress firewall. Install-time
protection applies to requests that actually reach its proxy. Warm package caches
and cached Dagger executions can skip those requests. The application pipeline has
separate fresh checks using empty package caches and a unique execution key; normal
builds reuse dependency layers. There is no retry without Socket.

## Updates and tests

`checksums.sha256` is shared with `backend/Dockerfile`, which verifies the downloaded
binary before running it. Renovate groups the release, checksum metadata and
Dockerfile URLs. `socket-pins` rejects version drift between them. Review changes to
the release and both GitHub-provided digests together.

From this repository:

```sh
just dagger-check --generated=false --check module-contracts --check socket-pins
just dagger-check --generated=false --check socket-python --check socket-cli --check socket-frontend
```

The contract fixture verifies argument/environment preservation and that a blocked
install fails. Fresh checks exercise the real Socket binaries with uv and pnpm.
They do not download a known-malicious package as a test.

Tested with Dagger beta.25 and Python SDK v1.7.0, generating the beta.24 API.
Before publishing, choose the module's license, move its tests into the publishing
repository's harness, and create an independent module release tag.
