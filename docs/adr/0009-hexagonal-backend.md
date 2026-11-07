# Hexagonal backend around a small domain

The backend's domain (Script Catalogue, Script Run, Check/Finding/Diagnostic Run, Audit Log) is plain Python and depends on nothing outside it. Kubernetes, PostgreSQL, OIDC and HTTP calls to Components are adapters behind ports. This lets the domain rules be developed test-first without a cluster: building Job specs from pod templates, mapping parameters to arguments, permission and Confirmation rules, and writing Audit Entries. Only the adapters need integration tests against kind.
