# EAOP 08F · Docker bridge parity review

The ID change from `56b12578649f` to `4bf1bda0a985` was Docker Desktop Resource Saver behavior. The host backend log records the idle timer expiring at 13:42:49 ET on November 16, 2026, and the VM stopping at 13:42:50. A Compose image lookup woke the VM at 13:43:08. The VM log records Docker Engine 29.7.2 starting at 13:43:10.601 ET and completing initialization at 13:43:11.416. The new network was created within that interval at 13:43:11.026. The old VM's proxy log records a GET for the old bridge ID at 13:42:50.103 ET before shutdown.

Docker's [bridge documentation](https://docs.docker.com/engine/network/drivers/bridge/) identifies `bridge` as the automatically created default network. The [Engine 29.7.2 startup code](https://github.com/moby/moby/blob/docker-v29.7.2/daemon/daemon_unix.go#L796-L839) clears the stale default bridge and initializes it again when there are no active sandboxes. The Compose lookup triggered wakeup; Docker Engine recreated its built-in network.

| Field | Retained baseline | Replacement (read-only inspect) |
| --- | --- | --- |
| Name and ID | `bridge`, `56b12578649f` | `bridge`, `4bf1bda0a985` |
| Driver and scope | Not recorded | `bridge`, `local` |
| Labels and role | Labels and options not recorded; name identifies Docker's built-in default | Empty labels; `com.docker.network.bridge.default_bridge=true`, interface `docker0` |
| Internal / attachable / ingress | Not recorded | False / false / false |
| IPAM and addresses | Not recorded | Default driver, no options, IPv4 `172.17.0.0/16`, gateway `172.17.0.1`; IPv6 disabled |
| Other driver options | Not recorded | ICC and masquerading enabled; host binding `0.0.0.0`; MTU 1500 |
| Created | Exact timestamp not recorded | `2026-11-16T18:43:11.02628111Z` |
| Attachments | Network endpoint map not recorded. The stopped `eaop-db-validation` container listed `bridge`. | Empty network endpoint map. This does not describe the stored network assignment of a stopped container. |

The [retained inventory](protected-resources.json) and [teardown record](2026-11-16-follow-up.md) support identity parity for both protected containers, ten volumes, fifteen images and three other networks (`enterprise-ai-operations-platform_default`, `host`, and `none`). Both containers remained exited with code 255. The custom network's full baseline configuration and the original bridge inspection payload were not retained. The lifecycle cause is established and benign; full configuration and attachment parity cannot be certified from these records.

For EAOP safety reviews, capture complete network inspections before and after scoped work. Require exact identity and configuration parity for protected and custom networks. For verified Docker built-ins, record ID and creation-time changes as lifecycle evidence and compare semantic configuration and attachments, including the stored network assignments of stopped protected containers. A missing baseline field is unverified. This rule does not turn the historical comparison into a pass.

The bridge-ID investigation is complete. The parity check remains incomplete, so the pending 08F change set stays uncommitted. Gate C remains closed. EAOP 08F remains open, EAOP 09 is premature, and SAFE TO CLEAR is No.

Owner disposition for this checkpoint: the missing historical inspection is a documented evidence limitation and is no longer a blocker to committing the local 08F batch. The historical configuration and endpoint comparison remains unverified. The requirement to capture full inspections applies to future parity checks.
