# Scripts run as one-off Kubernetes Jobs, not by exec into live pods

Every Script Run is a new Kubernetes Job. The Job is built from the pod template of the Component's Deployment, which the Script Catalogue entry names. It keeps the same image, environment (including secret references), volumes and service account. The container `command`/`args` are replaced with `python src/manage.py <command> <params>`.

## Considered Options

- **Exec into a running pod.** This is simpler and needs no pod-spec derivation. We rejected it for four reasons. It needs the broad `pods/exec` permission, which allows arbitrary commands. It shares resources with live traffic. A deploy or scale-down kills a Script mid-run. Its output is lost when the pod goes away.

## Consequences

- When deriving the Job, the tool must strip probes, ports and lifecycle hooks. It must replace pod labels so Service selectors don't match the Job pod, and keep only the init containers the catalogue marks as required. It must also handle sidecars so they don't block Job completion. The Job uses `restartPolicy: Never`, `backoffLimit: 0`, a per-Script `activeDeadlineSeconds` and `ttlSecondsAfterFinished`.
- The tool's RBAC (role-based access control) needs `jobs` create/get/delete and `pods/log` get in the Environment's namespace. It needs no `pods/exec`.
- A Script Run starts a few seconds slower than an exec would.
- Refined after research (`docs/research/podiumd.md`, PodiumD 4.10.x):
  - The pod template is copied from the live Component **web** Deployment (named `<fullname>`), never `-nginx`, `-worker` or `-beat`.
  - **All** volumes and mounts are copied.
  - No init containers are kept.
  - `workingDir` is set to `/app`, and `OTEL_SDK_DISABLED=True` is added.
  - Pod labels are fully replaced, so the Job pod is never added to a Component's Service endpoints or selected by its PodDisruptionBudget.
  - On clusters that enforce NetworkPolicies, the Script Run label must be allowlisted in the PodiumD values (`networkPolicies.protectBackends.extraFrom.*`). This is documented as a per-Environment values change and will be proposed upstream as a default.
