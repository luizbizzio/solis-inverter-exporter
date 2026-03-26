# Security Policy

## Supported Versions

Security updates are provided for the latest code on the default branch.

| Version | Supported |
| --- | --- |
| `main` | Yes |
| Older commits or forks | No |

## Reporting a Vulnerability

Please do **not** report security vulnerabilities through public GitHub issues.

Use one of these channels instead:

1. **GitHub Private Vulnerability Reporting** for this repository, if it is enabled.
2. If private reporting is not available, contact the maintainer privately through the contact method listed on the GitHub profile.

When reporting, include:

- A clear description of the issue
- Steps to reproduce it
- A proof of concept, if available
- Impact assessment
- Suggested remediation, if known

You can expect:

- An initial acknowledgment within **7 days**
- A best-effort investigation and triage
- Coordination on disclosure before public release

## Scope

This project is a Prometheus exporter that connects to Solis inverter web interfaces on a local network and exposes metrics over HTTP. Reports are especially relevant if they involve:

- Exposure of inverter credentials
- Leakage of device or network metadata
- Unauthorized access to exporter endpoints
- Unsafe defaults in configuration or container usage
- Denial of service through polling or malformed responses
- Dependency-related vulnerabilities with realistic impact on this project

## Out of Scope

The following are generally out of scope unless they directly create a security impact in this repository:

- Feature requests
- Installation problems without a security impact
- Missing hardening in a user's own Prometheus, Docker, reverse proxy, or LAN setup
- Issues that require physical access to the user's network or machine unless the project materially increases that risk
- Reports based only on outdated dependencies without a demonstrated exploit path or relevant impact

## Deployment Guidance

To reduce avoidable risk:

- Keep the exporter bound only to trusted interfaces unless remote access is intentionally required.
- Do not publish the exporter directly to the public internet.
- Protect configuration files because they may contain inverter credentials.
- Review whether optional network or device info metrics should be enabled in your environment.
- Restrict access to Prometheus, dashboards, logs, and backups that may expose sensitive operational data.
- Keep Python, container base images, and dependencies up to date.

## Disclosure Policy

Please allow reasonable time for investigation and remediation before disclosing details publicly.

Public disclosure before a fix is available may put users at unnecessary risk.
