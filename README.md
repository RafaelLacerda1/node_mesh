# Network Node Monitor

Web-based management and monitoring platform for TV Box devices operating in an isolated ad-hoc wireless mesh network.

The system provides centralized monitoring, node discovery, remote command execution, user management, web terminal access, audit logging, and offline software package distribution.

## Overview

The infrastructure consists of a central management VM, a gateway, and multiple TV Box nodes connected through an isolated ad-hoc wireless network.

```text
Management VM
      |
 SSH / Ansible
      |
   Gateway
      |
Ad-hoc Mesh Network
   /    |    \
Node  Node   Node
```

A key architectural requirement is that communication between the management VM and TV Box nodes passes through the gateway.

## Main Features

### Node Discovery

The system can automatically discover devices connected to the mesh network.

Features include:

- Network scanning through the gateway.
- Device discovery using network neighbor information.
- Node database updates.
- Node availability tracking.
- Missed-scan tolerance before marking a node offline.

### Node Monitoring

The dashboard provides centralized information about managed nodes and their current availability.

### Remote Command Execution

Administrators can execute commands remotely on selected TV Box nodes through Ansible.

The application dynamically creates the Ansible inventory, configures SSH communication through the gateway, executes commands, processes results, and handles partial failures.

### Web Terminal

The project integrates with a separate WebSSH service to provide terminal access through the web interface.

Nginx acts as the reverse proxy between the Flask application and WebSSH.

### Authentication and User Management

The application provides authentication and administrative access control using:

- Flask-Login
- Bcrypt
- Administrative role checks

### Audit Logging

Administrative actions are recorded in per-user audit logs.

## Offline Package Installation

One of the main features is the ability to install Debian packages on TV Box nodes without requiring direct Internet access on those nodes.

The management VM obtains the packages and dependencies. Ansible then distributes and installs them on the nodes.

```text
Management VM
      |
Package resolution
      |
Local package cache
      |
    Ansible
      |
   Gateway
      |
Ad-hoc Mesh Network
   /    |    \
Node  Node   Node
```

### Installation Pipeline

```text
Resolving
    |
Validating
    |
Downloading
    |
Distributing
    |
Installing
    |
Completed / Partial / Failed
```

Long-running installations execute as background jobs and their status can be monitored through the web interface.

### Node Compatibility Validation

Nodes are validated before installation.

The current environment targets:

- Debian Bullseye
- ARM64 architecture

Incompatible nodes are skipped instead of receiving an installation attempt.

### Package Cache

Downloaded `.deb` packages are stored in a persistent local cache.

A JSON manifest tracks cached packages.

When a package is already cached, the system can reuse it without downloading it again.

The cache mechanism was validated in the real environment.

## External Package Support

The package system was designed to support different package acquisition methods.

The external package catalog can define:

- Package type
- Download method
- Installation method
- Optional APT repository configuration

The gateway can be used as an intermediate point for downloading external packages before they are transferred to the management VM and distributed to TV Box nodes.

## Network Architecture

The official communication flow is:

```text
VM
 |
 | SSH / Ansible
 v
Gateway
 |
 | Ad-hoc wireless network
 v
TV Box nodes
```

The management VM does not communicate directly with mesh nodes.

The gateway acts as:

1. The discovery execution point.
2. The SSH/Ansible jump point for communication with TV Box nodes.

This architecture is required because the mesh network is isolated from the management network.

## Technology Stack

### Backend

- Python
- Flask
- SQLAlchemy
- Flask-Login
- Bcrypt
- SQLite

### Automation

- Ansible
- ansible-runner
- SSH
- Ansible Playbooks

### Infrastructure

- Linux
- Docker
- Docker Compose
- Nginx
- Ad-hoc wireless mesh networking

### Frontend

- HTML
- CSS
- JavaScript
- Flask templates

### Storage

- SQLite
- JSON manifests
- Local package cache
- Audit logs

## Project Architecture

```text
app/
├── routes/
├── services/
├── models/
├── utils/
├── config.py
├── extensions.py
└── __init__.py

ansible/
└── playbooks/

static/
templates/

data/
```

Main services:

- `DiscoveryService` — network discovery and node state.
- `AnsibleService` — remote node operations.
- `PackageService` — package validation, caching, distribution and installation.
- `AuditService` — administrative audit logging.

The application follows a modular Flask architecture separating routes, services, models and utilities.

## Reliability and Fault Handling

The platform was designed for environments where some nodes may be temporarily unavailable.

Features include:

- Per-node operation results.
- Partial failure handling.
- Offline node detection.
- Incompatible node skipping.
- Asynchronous package jobs.
- Explicit job states.
- Protection against concurrent package installations.

## Validation

The system was validated against the real deployment environment.

Validation included:

- Real node discovery.
- Real Ansible communication.
- Real package installation.
- Multiple-node installation.
- Offline node handling.
- Incompatible architecture handling.
- Package cache reuse.
- Concurrent installation protection.
- HTTP route regression testing.
- Docker deployment.
- Gateway-based SSH communication.

A real Debian package installation was successfully performed on a TV Box, followed by a second installation using the existing package cache.

The installation workflow was also tested across multiple TV Box nodes.

## Example Use Cases

### Discover Nodes

An administrator can trigger a discovery scan from the web interface to identify devices currently present in the mesh network.

### Execute a Command

An administrator can select nodes and execute a remote command through the management platform.

### Install a Package

The administrator can:

1. Select one or more nodes.
2. Enter the package name.
3. Validate the package.
4. Start the installation.
5. Monitor the background job.
6. Review the result for each node.

### Review Previous Operations

The package management interface provides a paginated list of previous installation jobs and their results.

## Screenshots

Recommended screenshots:

```text
docs/images/dashboard.png
docs/images/discovery.png
docs/images/packages.png
docs/images/terminal.png
```

Example:

```markdown
![Dashboard](docs/images/dashboard.png)
```

## Running Locally

### Python

Install the project dependencies and run:

```bash
python run.py
```

The application runs on:

```text
0.0.0.0:8080
```

### Docker

Build and start the application:

```bash
docker compose up --build
```

The Docker deployment includes the Flask application and Nginx reverse proxy.

## Security Notes

This project was developed for a controlled laboratory environment.

Environment-specific settings should be configured before adapting the project to another infrastructure.

Do not commit:

- Private SSH keys
- Passwords
- API tokens
- Environment secrets
- Production credentials
- Sensitive infrastructure configuration

## My Contribution

I participated in the development and evolution of the platform, working with:

- Python and Flask
- Software architecture
- Linux systems
- Computer networks
- Ansible automation
- SSH and ProxyCommand
- Docker
- Nginx
- SQLite
- JavaScript
- Network discovery
- Remote system management
- Package distribution and installation
- Infrastructure troubleshooting

A significant part of the work involved investigating the real network topology and adapting the Ansible communication layer to use the gateway as the required path to the mesh nodes.

The project was tested and validated against real TV Box devices in the deployed mesh environment.

## Project Status

The core monitoring, discovery, remote management, and offline package installation workflows have been implemented and validated in the target environment.

The project continues to evolve as new infrastructure and management requirements are identified.

## License

This project is intended for academic and research purposes.
