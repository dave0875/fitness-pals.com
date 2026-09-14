# DEV Docker network recovery

The DEV runtime must have one Docker daemon owning its containers and networks.
Two daemons sharing a host network namespace can overwrite host-global firewall
chains. If the daemon that rewrites those chains does not own the application's
user-defined bridge, forwarding can fail even when the containers and bridge are
healthy. A host forwarding policy that defaults to DROP can then block both
peer traffic and container egress.

This guide intentionally uses placeholders. Resolve the owning daemon, duplicate
service/socket, application bridge, and any temporary firewall rule from the
host's current inventory and change record; do not copy identifiers from an
example or infer them from old logs.

## Before changing daemon state

Use the normal operator access path and a planned maintenance window. Record:

- Running containers, health, restart policies, networks, and named volumes.
- Which daemon owns the application containers, networks, and persistent data.
- The duplicate daemon's service and socket units, if present.
- The application bridge interface and the exact temporary rule, if present.
- The self-hosted runner state and the checkout used to reconcile DEV.

Do not remove or recreate volumes, prune Docker resources, reset databases, or
change the host-wide forwarding policy. A daemon restart does not require volume
recreation. If ownership or the duplicate service is unclear, stop and resolve
that before making changes.

## Durable repair

Keep the daemon that owns the application data and runtime as the sole Docker
network owner. Disable and mask only the confirmed duplicate service and its
socket, then restart the owning daemon so it can regenerate rules from its
persisted network state. Substitute values verified in the current host
inventory; these commands are templates, not literal unit names:

```bash
sudo systemctl disable --now <duplicate-docker-service> <duplicate-docker-socket>
sudo systemctl mask <duplicate-docker-service> <duplicate-docker-socket>
sudo systemctl restart <owning-docker-service>
```

After the daemon returns, reconcile the complete DEV Compose runtime from its
normal deployment checkout. Some application containers may not restart
automatically, so verify and restore the expected services through the normal
deployment path.

## Verification

Confirm that the duplicate units are masked and inactive, the owning daemon is
active, and only the expected daemon is managing the application runtime. Check
that regenerated Docker forwarding chains include the application bridge and
that the temporary incident rule is still present while validation is underway.

With the temporary rule still in place, confirm fresh-container DNS and TCP
access to the required peer services, plus outbound HTTPS. Validate the complete
DEV service set and its readiness checks. If any probe fails, keep the
temporary rule and restore service through the established rollback path; do not
broaden the rule or change the host forwarding policy.

Only after the durable Docker rules are verified and the same probes pass without
the temporary exception should an operator remove that one exact rule. First
locate and confirm the exact match; never flush the user-defined chain or delete
rules by an assumed line number. Repeat the probes without the exception, then
confirm application health and the expected database migration state.

After the next planned host reboot, repeat daemon ownership, firewall, peer,
egress, and service checks. Treat a change of Docker distribution or data root
as a separate migration; never point a second daemon at another daemon's data.
