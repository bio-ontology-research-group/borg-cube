# Playbook: incident response

When: `hermes-ws` `infra-check` reports DOWN after two consecutive failures
(event -> `kind:incident` bead with `host:<name>` and `service:<id>`), the
infra-hygiene patrol raises a finding, or Robert asks. Role: sysadmin.

1. Confirm: `infra.py status`, `infra.py events 30`, `infra.py test NAME`;
   quote state, since when, message.
2. Scope: external (a public URL users notice) versus internal (a cause).
   Lead with the external effect and name the URL.
3. Investigate read-only on the host (BatchMode ssh, logs, `docker ps -a`,
   `systemctl status`, `journalctl --since`). KAUST DMZ VMs are not
   ssh-reachable from ws; report and say a human must log in with the admin
   account.
4. Report: what is down, since when, most likely cause, the exact command
   that would fix it, quoted back. This is where the run ends unless Robert
   asks for the action.
5. Act only on an explicit ask, one quoted command at a time; never
   `scancel`, delete, kill, restart or edit config otherwise.
6. Follow-up: config changes become PRs into `borg-infrastructure` through the
   review gate; inventory updates proposed for `deployment/ip_addresses.md`
   and `unimatrix/CLUSTER_CONFIG`.
7. Close: incident report attached to the bead; the finding closes when
   `infra-check` reports UP.

Runbooks: `PAVS_MAINTENANCE.md`, `RUBALKHALI_MAINTENANCE.md`,
`borg-server2-migration.md`, `unimatrix/KNOWN_ISSUES.md`, `office-ws/README.md`
(ssh route host-key recovery). Secrets are referenced by path only.
