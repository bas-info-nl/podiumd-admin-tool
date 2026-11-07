# PodiumD Admin Tool

A web app that lets a municipality's administrators manage, operate and diagnose their own PodiumD installation.

## Language

### Platform

**PodiumD**:
Dimpact's Common Ground platform. It is a set of **Components** deployed together with a single Helm chart.
_Avoid_: the platform, the stack

**Component**:
One application that is part of PodiumD, such as Open Zaak, Objecten, Open Formulieren, KISS, ZAC or Keycloak.
_Avoid_: app, service, module

**Municipality**:
The organisation that owns and administers one set of PodiumD **Environments**.
_Avoid_: tenant, customer, gemeente (in code)

**Environment**:
One deployed instance of PodiumD belonging to a **Municipality**, identified by its stage: `test` (optional), `accp` or `prod`. Each **Municipality** has at least `accp` and `prod`. Every **Environment** runs in its own cluster.
_Avoid_: installation, stage, cluster, namespace

**Admin Tool Instance**:
The copy of the admin tool installed in one **Environment**. It can only see and manage that **Environment**.
_Avoid_: central admin, portal

### Configuration

**Values Repository**:
The Git repository holding the Helm values for a **Municipality's** **Environments**. It is the source of truth for configuration, and a deployment pipeline applies it to the cluster.
_Avoid_: config repo, GitOps repo

**Deployment Configuration**:
The Helm values that determine how each **Component** in an **Environment** is deployed. The **Admin Tool Instance** never changes it, and only shows it in the form of **Effective Settings**.
_Avoid_: settings, values (unqualified)

**Effective Settings**:
The settings a running **Component** actually received in the **Environment**: its environment variables and mounted configuration. Values that come from secrets are left out. Other values are shown only for settings known to be safe, and the rest are masked. This shows what is running now, not what is in the **Values Repository**.
_Avoid_: live config, Helm values

**Runtime Configuration**:
Configuration a **Component** keeps in its own storage and that is changed through that Component's admin interface, such as catalogi, autorisaties, abonnementen or Keycloak clients. The **Admin Tool Instance** shows it but never changes it.
_Avoid_: app settings, admin config

### Operations

**Script**:
A named, predefined command with typed parameters, belonging to one **Component**. The command already exists in that Component's container image; for Django **Components** such as Open Zaak, Objecten and Open Notificaties it is a `manage.py` command. Admins choose a **Script** and fill in its parameters. They never type a free-form command.
_Avoid_: job, task, command (unqualified), action

**Script Catalogue**:
The set of **Scripts** available in an **Environment**. It is supplied to the **Admin Tool Instance** through its Helm values and changes with each PodiumD release.
_Avoid_: script registry, allowlist

**Script Run Output**:
The console output a **Script Run** produced. It is kept separately from the **Audit Log** and linked to the **Script Run** it belongs to.
_Avoid_: script log, job log, audit (for output)

**Dangerous Script**:
A **Script** whose effects can't be undone, such as importing or deleting data. Before a **Script Run** of it starts, the **Operator** starting it must give an explicit **Confirmation**.
_Avoid_: destructive script, unsafe script

**Script Run**:
One execution of a **Script** with specific parameter values, started by one admin in one **Environment**. It is a separate, short-lived process and never runs inside a live **Component**. It ends as `succeeded`, `failed`, `timed out` or `cancelled`. Unless the **Script** allows it, only one **Script Run** of a given **Script** can be active at a time in an **Environment**.
_Avoid_: execution, job (in domain language)

**Confirmation**:
The explicit, recorded consent an **Operator** gives right before starting a **Script Run** of a **Dangerous Script**, after reviewing its parameters. It is given by the same person who starts the run.
_Avoid_: approval (reserved for future four-eyes review by a second person)

### Diagnostics

**Check**:
A named, read-only test of one aspect of an **Environment**, such as workload health, version consistency, connectivity between **Components**, or external URLs. A **Check** never changes anything.
_Avoid_: test, probe, rule, validation

**Finding**:
The result of one **Check**: a severity (`ok`, `warning`, `error`), a message, and where possible a hint on how to fix it.
_Avoid_: issue, alert, result (unqualified)

**Diagnostic Run**:
One execution of a set of **Checks** against the **Environment**, producing one **Finding** per **Check**. Its outcome is stored.
_Avoid_: scan, health check, audit

### Access and accountability

**Viewer**:
A role that can see **Effective Settings**, **Diagnostic Runs**, **Script Run** history and the **Audit Log**, but cannot start **Script Runs**.
_Avoid_: reader, read-only user

**Operator**:
A role that can do everything a **Viewer** can, and can also start **Script Runs**, including of **Dangerous Scripts** after **Confirmation**.
_Avoid_: admin, maintainer, superuser

**Audit Log**:
The append-only record of sign-ins, sign-outs and session expiries, and of every action a user attempted in an **Admin Tool Instance**, whether allowed or denied. It consists of **Audit Entries** and never contains **Script Run Output**.
_Avoid_: history, activity log, event log

**Permission**:
A named right to perform a read or an action, such as `audit-log:read`, held by one or more roles (**Viewer**, **Operator**).
_Avoid_: right, privilege, scope

**Session**:
The period a user is signed in to one **Admin Tool Instance**. It starts at sign-in and ends at sign-out or expiry.
_Avoid_: login, token

**Audit Entry**:
One record in the **Audit Log**: who did or attempted what, when, in which **Environment**, with which parameters, and whether it was allowed or denied.
_Avoid_: log line, event

## Flagged ambiguities

- "Manage application configuration" was ambiguous. Resolved: the **Admin Tool Instance** only _views_ **Deployment Configuration** and **Runtime Configuration**. Secrets are never shown or edited. A **Check** may only compare two copies of a shared credential and report whether they match.
- "Installation" was used loosely to mean either everything a **Municipality** runs or a single deployment. Resolved: use **Municipality** for the owner and **Environment** for a single deployment.
- "Approval" for **Dangerous Scripts** could mean a second person or the person starting the run. Resolved: in v1 it is a **Confirmation** by the starting **Operator** themselves. Approval by a second person (four-eyes) is deferred, and the word "approval" is kept for that future concept.
