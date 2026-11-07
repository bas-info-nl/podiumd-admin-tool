# Audit Log is stored in the tool's own database and also written to stdout

Each Admin Tool Instance has its own PostgreSQL database. It holds the Audit Log (user logins, and allowed and denied actions) and, kept separately, the Script Run Output. The Script Run Output has to be preserved because Script Run Jobs and their pod logs are deleted after `ttlSecondsAfterFinished`. Every Audit Entry is also written to stdout as a structured JSON line, so that a log scraper can pick it up if the cluster has one. Whether a scraper exists is outside this tool's scope.

The database lets the UI show history and Script Run Output. The stdout copy is an independent trail that the tool itself cannot rewrite. The application has no code paths that update or delete Audit Entries. Retention is deliberately not addressed yet.
