# The Admin Tool's cluster access is strictly limited to the PodiumD namespace

The Admin Tool gets no RBAC outside the PodiumD namespace of its Environment. This also excludes read access to the Gateway API HTTPRoutes in `ingress-basic`, where the public hostnames are defined. Instead, the Check for host consistency compares Component settings (ALLOWED_HOSTS, OIDC URLs, CSRF origins and so on) against the expected public hostnames supplied in the Admin Tool's Helm values. Where it helps, the Check adds external probes over DNS/TLS/HTTP.

We chose this over a narrow read-only Role in `ingress-basic`. It keeps the tool's footprint, and what Dimpact must review before adopting it, to one namespace. The cost is that the expected hostnames are a second copy that must be kept in step with the deploy-side routes. A drift between that copy and the real routes shows up as a Finding, not as a silent pass.
