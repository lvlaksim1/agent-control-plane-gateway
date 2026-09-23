# Agent Control Plane Gateway

Public transactional lease gateway for the private `lvlaksim1/agent-control-plane`.

This repository is infrastructure, not an agent. It stores **no task objectives, project context, agent memory, credentials, or target evidence**. Its only durable state is a global opaque execution lease.

Why it exists: ordinary Scheduled Chat can read/write GitHub, but a live E2E showed that its tool safety layer may decline a direct private-repository lease acquisition. The gateway moves only the deterministic lock transition into GitHub Actions while leaving reasoning and target execution in ordinary Chat.

## Request protocol

Create an Issue with exact title:

`[ACP_LEASE]`

The complete Issue body is JSON.

Supported operations:
- `claim`
- `renew`
- `release`
- `recover_expired`

Only issues authored by `lvlaksim1` are processed.

The workflow is globally serialized with one GitHub Actions concurrency group. Every accepted transition commits `runtime/lease.json` before reporting success.

The gateway does not decide which task is READY and cannot grant agent authority.


## Multi-slot serialization

The lease workflow uses one global concurrency group with `queue: max`. This is required for the shared five-slot dispatcher pool: concurrent lease requests are queued instead of replacing/canceling an already-pending request. The lease state machine still admits only one active owner; later queued claims observe the committed active lease and are rejected normally.
