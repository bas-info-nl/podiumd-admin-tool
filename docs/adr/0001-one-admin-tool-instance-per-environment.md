# One Admin Tool instance per Environment

Each Environment of a Municipality runs in its own Azure Kubernetes cluster. The Admin Tool is installed separately in every Environment, and each instance can only see and manage the Environment it is installed in. Its frontend is opened from a URL specific to that Environment.

We chose this over one central instance per Municipality because an instance in accp then has no route to prod. That isolation matters most for running scripts in containers. It also means no credentials or network paths are needed between clusters, and each instance can sign users in through its own Environment's identity provider.

## Consequences

- No cross-Environment view, such as comparing accp with prod, can come from live clusters. If we add one later, it has to be built from the Values Repository.
- The Admin Tool is deployed and upgraded once per Environment, the same way PodiumD itself is.
