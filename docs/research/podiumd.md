# PodiumD research for the Admin Tool

## Summary

- **Chart version.** The research read **podiumd 4.10.0** (tag `podiumd-4.10.0`, commit `eecb376136a29e7ec3162bd609bf5a480f787ab0`, 2026-10-26).
  - **podiumd 4.10.1** (tag `podiumd-4.10.1`, commit `513c5fd20c066ccb5b24775fee56bac8c4ffed27`, 2026-11-05) is now the latest release. `main` is at the same commit.
  - The 4.10.1 changes were diffed against everything below. The image layout, the management command lists and the connectivity settings did not change. Details are in Sources & chart version.
- **Ten Django Components.** openzaak, opennotificaties, objecten (Open Object 4.3.0, which merges Objecten and Objecttypen), openklant, openformulieren and openinwoner are on by default. openarchiefbeheer, referentielijsten, openbeheer and openvtb are **off by default**. The Script Catalogue must hide Components that are not deployed.
- **Several Deployments per Component.** Each Component has separate web, worker, beat and flower Deployments. For six Components, nginx is also a separate Deployment, not a sidecar. Script Jobs must be derived from the **web Deployment** (named `<fullname>`, main container `containers[0]`). Never derive from `-nginx`, `-worker` or `-beat`.
- **Shared image layout.** All 10 images use `WORKDIR /app`, keep the source at `/app/src`, have no ENTRYPOINT, use `CMD ["/start.sh"]` and run as uid 1000. `/app/src/manage.py` is executable. `/start.sh` always runs `migrate` (and sometimes fixtures or a superuser), so command and args **must** be overridden.
- **No init container is required for Scripts.** The only enabled init container is openinwoner `openinwoner-search-index`, which runs migrate and a full ES reindex. It must be dropped. Under the agreed rule "only required init containers kept", the result is zero init containers for all 10 Components.
- **No sidecars on Django pods** in the chart. There is no service mesh, and the OpenBao injector is off. ZAC has an OPA sidecar, but ZAC has no manage.py.
- **Volumes must come from the live Deployment, not chart defaults.** Two cases matter:
  - Open Forms `verify-certs` is supplied by each environment.
  - Open Archiefbeheer has a `PYTHONPATH` patch ConfigMap (open-archiefbeheer#1103).
- **Labels must be replaced.** A Job pod that keeps `app.kubernetes.io/name: <app>` joins the Service endpoints and the PDB selection. NetworkPolicies (where enforced) allow Redis and ClamAV only by name label. Allowlist a dedicated Script label through `networkPolicies.protectBackends.extraFrom.*`.
- **NetworkPolicy enforcement differs per cluster.** Some clusters run a policy engine and others don't. Check each Environment; don't assume either way.
- **Public hostnames come from Gateway API HTTPRoutes** (`hr-<app>-nginx`) in namespace `ingress-basic`, created on the deploy side. They are not Ingresses in the podiumd namespace. A host-consistency Check needs read access outside the app namespace.
- **Most edges between Components are runtime-only.** They are zgw-consumers rows in the Component DBs. The desired state can be parsed from ConfigMap `<fullname>-configuration`. Env-visible edges exist only for ZAC, KISS, ITA, PABC, the adapter, OMC, the office add-in and the infrastructure (Redis, Postgres, ES, SMTP).
- **Strongest shared-credential Check.** Compare Keycloak `keycloak-podiumd-realm-secrets[<comp>-oidc-secret]` with `<comp>-config-secrets[keycloak_client_secret]`. If the configured values are empty, Helm generates a random value for the realm side while the Component side stays `""`, and `validations.yaml` does not catch this for Maykin Components.
- **Several suspected credential pairs cannot be compared.** For ZAC, KISS, ITA, OIP and OAB credentials toward Open Zaak, the Open Zaak copy exists only in the Open Zaak DB.

## Sources & chart version

| Item                 | Version / ref                                                                                                                                                                                                                                                      | Source                                                                                                                                                                                                |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Umbrella chart read  | `podiumd-4.10.0` = `eecb376136a29e7ec3162bd609bf5a480f787ab0`                                                                                                                                                                                                      | https://github.com/Dimpact-Samenwerking/helm-charts/blob/podiumd-4.10.0/charts/podiumd/Chart.yaml                                                                                                     |
| Latest release       | `podiumd-4.10.1` = `513c5fd`, 2026-11-05                                                                                                                                                                                                                           | https://github.com/Dimpact-Samenwerking/helm-charts/blob/podiumd-4.10.1/charts/podiumd/Chart.yaml ; diff: https://github.com/Dimpact-Samenwerking/helm-charts/compare/podiumd-4.10.0...podiumd-4.10.1 |
| Maykin subcharts     | openzaak-1.14.2, opennotificaties-2.1.0, openobject-1.2.0 (alias `objecten`), openklant-1.11.0, openforms-1.13.0 (alias `openformulieren`), openinwoner-2.6.0 (2.7.0 in 4.10.1), openarchiefbeheer-2.1.0, openbeheer-0.1.3, referentielijsten-0.2.0, openvtb-0.2.0 | `https://github.com/maykinmedia/charts/blob/<chart>-<ver>/charts/<chart>/` and release `.tgz` assets                                                                                                  |
| Other charts         | zaakafhandelcomponent 1.0.355, kiss-chart 3.2.0, internetaakafhandeling 3.3.4, pabc 2.1.0, notifynl-omc-nodep 0.17.4, zgw-office-addin 0.0.93 (OCI/release packages). zaakbrug 2.3.33 was **not read** (4.10.1 pins 2.3.36)                                        | as listed                                                                                                                                                                                             |
| Component image tags | open-zaak 1.29.3, open-notificaties 1.17.0, open-object 4.3.0, open-forms 4.0.2 (4.0.7 in 4.10.1), open-klant 2.15.0, open-inwoner v2.4.7 (2.5.0 in 4.10.1), open-archiefbeheer 2.0.0, open-beheer 0.9.1, open-vtb 0.2.0, referentielijsten 0.7.5                  | e.g. https://github.com/open-zaak/open-zaak/blob/1.29.3/Dockerfile                                                                                                                                    |

**What 4.10.1 changes:**

- Chart pins: openinwoner 2.6.0 → 2.7.0, zaakbrug 2.3.33 → 2.3.36, openbao 0.30.3 → 0.30.6.
- Image tags: Open Forms 4.0.2 → 4.0.7, Open Inwoner 2.4.7 → 2.5.0.
- New template `templates/zac-restart-after-openzaak-config.yaml`.
- Changes to `networkpolicies.yaml`, the Keycloak jobs and `objecttypen-compat-service.yaml`. These were **not re-read in detail**.
- Diffed and found layout-neutral:
  - The Dockerfiles, `manage.py`, `conf/docker.py` and the command lists are unchanged.
  - OIP `start.sh` adds `uwsgi --lazy-apps`.
  - The OIP chart 2.7.0 only adds a beat livenessProbe and touches no connectivity settings.

**Abbreviations:**

- `HC` = `https://github.com/Dimpact-Samenwerking/helm-charts/blob/podiumd-4.10.0/charts/podiumd`
- `MK(<tag>)` = `https://github.com/maykinmedia/charts/blob/<tag>/charts/<chart>`
- `ZAC` = `https://github.com/infonl/dimpact-zaakafhandelcomponent/blob/zaakafhandelcomponent-1.0.355/charts/zac`

## Workloads & sidecars

### Components (HC/Chart.yaml)

| values key        | Chart                                | Enabled by default | Source                           |
| ----------------- | ------------------------------------ | ------------------ | -------------------------------- |
| openzaak          | openzaak-1.14.2                      | yes                | HC/Chart.yaml                    |
| opennotificaties  | opennotificaties-2.1.0               | yes                |                                  |
| objecten          | openobject-1.2.0 (Open Object 4.3.0) | yes                | HC/values.yaml l.1201-1225, 1418 |
| openklant         | openklant-1.11.0                     | yes                |                                  |
| openformulieren   | openforms-1.13.0                     | yes                |                                  |
| openinwoner       | openinwoner-2.6.0                    | yes                |                                  |
| openarchiefbeheer | openarchiefbeheer-2.1.0              | **no**             | HC/values.yaml l.1464            |
| referentielijsten | referentielijsten-0.2.0              | **no**             | l.2569                           |
| openbeheer        | openbeheer-0.1.3                     | **no**             | l.2679                           |
| openvtb           | openvtb-0.2.0                        | **no**             | l.2860                           |

**Other dependencies (not Django, so Scripts do not apply):**

- zac 1.0.355 (image 5.9.1, Chart.yaml l.71), kiss 3.2.0, ita 3.3.4, pabc 2.1.0, zgw-office-addin 0.0.93.
- keycloak-operator 1.13.1, clamav 3.7.3, redis-operator 0.27.0, eck-operator 3.5.0.
- Optional: omc, zaakbrug, brppersonenmock, mi, openbao.

**Objecttypen compatibility.** `objecttypenCompatService.enabled: true` (HC/values.yaml l.1210; HC/templates/objecttypen-compat-service.yaml) keeps the old `objecttypen` Service name pointing at the objecten pods.

### Shared Maykin pod structure

Verified in MK(openzaak-1.14.2)/templates/deployment.yaml, `_helpers.tpl` L55-57, `service.yaml` and `pdb.yaml`:

- **Deployments.** web, nginx (for OZ/OF/OK/OIP/OAB/OB), worker, flower (optional) and beat are separate Deployments from one `deployment.yaml`. nginx is `nginxinc/nginx-unprivileged` in its own Deployment.
- **Labels.** Pods carry only `app.kubernetes.io/name: <fullname>`. The Service and the PDB select on that same label.
- **Annotations.** `checksum/configmap` and `checksum/secret`.
- **Web container.** Named `{{ .Chart.Name }}`, which with a Helm alias is the alias, so it equals the Deployment name. For OAB it is the fullname.
- **Env.** `envFrom: [secretRef <app> (or existingSecret), configMapRef <app>]` plus `extraEnvVars`.
- **ServiceAccount.** `<app>`.
- **Volumes.** Media PVC (existingClaim `<app>`, storageClass `podiumd-standard`, ReadWriteMany per `podiumd.storagePVC` in HC/templates/_helpers.tpl; accessModes line and CSI driver not seen) plus `extraVolumes`/`extraVolumeMounts`.
- **securityContext.** Chart default: drop ALL, `readOnlyRootFilesystem: false`, runAsNonRoot, runAsUser 1000, podSecurityContext `fsGroup: 1000` (MK(openzaak-1.14.2)/values.yaml l.158-168). podiumd adds `allowPrivilegeEscalation: false` and `seccompProfile: RuntimeDefault` (HC/values.yaml l.674-680, WH-02). No Django Component has a read-only root filesystem.
- **Init container hooks.** The upstream charts have none, with two exceptions:
  - openinwoner: `settings.searchIndexInitContainer` and `cms4MigrationInitContainer` (MK(openinwoner-2.6.0)/templates/deployment.yaml L35-100).
  - openklant: `configuration.initContainer.enabled` (MK(openklant-1.11.0)/templates/deployment.yaml L35-75). It runs migrate, envsubst and setup_configuration, and envFroms `<fullname>-config-secrets`.

### Per-Component specifics

| Component         | Init containers (podiumd defaults)                                                                                                                                                                                             | Extra volumes / env to preserve                                                                                                                                                                                                                                                                                                                                                        | Source                                                                                 |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| openinwoner       | `openinwoner-search-index`: `/wait_for_db.sh; manage.py migrate; manage.py search_index --rebuild -f` (`searchIndexInitContainer: true`). `cms4MigrationInitContainer: false` because it crashes with a FieldError since 2.4.5 | —                                                                                                                                                                                                                                                                                                                                                                                      | HC/values.yaml l.2411, l.2418; MK(openinwoner-2.6.0)/templates/deployment.yaml l.70-92 |
| openklant         | config init container disabled (`configuration.initContainer.enabled: false`)                                                                                                                                                  | —                                                                                                                                                                                                                                                                                                                                                                                      | HC/values.yaml l.1717-1718                                                             |
| objecten          | config init container disabled                                                                                                                                                                                                 | worker ConfigMap `objecten-worker-celery` (worker pods only)                                                                                                                                                                                                                                                                                                                           | HC/values.yaml l.1238-1239                                                             |
| openformulieren   | none                                                                                                                                                                                                                           | ConfigMap volume `openformulieren-configuration` (deployment.yaml L103-106); `/srv/static/` (staticFileServing default true, MK(openforms-1.13.0)/values.yaml L614-616). The `verify-certs` volume (ConfigMap `openformulieren-verify-certs` at `/etc/ssl/verify-certs`) and `extraVerifyCerts` are **supplied per environment, not chart defaults** (HC/ci/lint-values.yaml L140-150) | as cited                                                                               |
| openarchiefbeheer | none                                                                                                                                                                                                                           | `PYTHONPATH=/opt/podiumd-patches` plus ConfigMap `openarchiefbeheer-patches` mounted read-only. It loads `sitecustomize.py` (workaround for open-archiefbeheer#1103). These are set through extraEnvVars/extraVolumes, so environment overrides of those lists must repeat the items                                                                                                   | HC/values.yaml l.1630-1645; HC/templates/openarchiefbeheer-patches.yaml                |
| others            | podiumd sets `configuration.initContainer.enabled: false` for openzaak (l.694), opennotificaties (l.975), openinwoner (l.2206; has no effect) and referentielijsten (l.2572)                                                   | —                                                                                                                                                                                                                                                                                                                                                                                      | HC/values.yaml                                                                         |

**CronJobs in the charts:**

- ON `cronjob-clean-notifications.yaml` is gated by `settings.cleanOldNotifications.enabled`, default false (MK(opennotificaties-2.1.0)/values.yaml l.352-354). podiumd does not set it.
- OF `cronjob-clean-logs.yaml` is gated by `settings.cleanLogs.enabled`, default false.
- So neither CronJob runs in a default PodiumD.

### Non-Django workloads

- **ZAC.** `zac.opa.sidecar: true` (HC/values.yaml l.3645). On ZAC `main` (chart 1.0.371), `charts/zac/templates/deployment.yaml` has init container `init-solr-zac-core` and adds the OPA container when `opa.sidecar` is set.
  - Confidence: **medium**. The template at the pinned 1.0.355 was not opened, although tag `zaakafhandelcomponent-1.0.355` exists.
- **ITA.** A web Deployment plus two "poller" CronJobs that share the ITA ConfigMap and Secret.
- **PABC** (k8s-wait-for init container), **KISS**, the office add-in, Keycloak, Redis and ECK: **UNVERIFIED** pod structure.

### Service mesh, injection, NetworkPolicies

- **No Istio or Linkerd configuration** was found. The OpenBao Vault Agent injector is explicitly off ("PodiumD does NOT use sidecar injection", HC/values.yaml l.5208-5212). A full-repo mesh search was not run.
- **Policy engine per cluster** (see HC/docs/misc/network-policy-analysis.md): enforcement varies between clusters. Some run Cilium and enforce NetworkPolicies; on others, NetworkPolicies are not enforced. The Admin Tool must work in both cases, and installers must check this per Environment.
- **`templates/networkpolicies.yaml`** is gated by `networkPolicies.enabled` (default false, HC/values.yaml l.5590). `protectBackends.enabled` defaults to true.
  - **Redis HA ingress on 6379** (L105-190) is allowed from:
    - `app.kubernetes.io/name` in the web, `-worker`, `-beat`, `-celery-monitor`, `-low-latency-worker` and `-config` names of every Django app;
    - podiumd Jobs (`app.kubernetes.io/name: podiumd` with component in [openformulieren, openinwoner]);
    - the frankgateway oauth2-proxy, the Redis pods themselves and the redis-operator;
    - `extraFrom.redis`.
  - **ClamAV ingress on 3310** (L457-498) is allowed from openformulieren(-worker), openinwoner(-worker), the same podiumd Jobs, and `extraFrom.clamav`.
  - **There are no egress policies.**
  - **Extension hook:** `networkPolicies.protectBackends.extraFrom.{redis,clamav,...}` (HC/values.yaml L5608-5617).

### Precedent: Dimpact's own manage.py Jobs

HC/templates/openformulieren-configure-clamav.yaml and openinwoner-configure-kvk.yaml build a Job pod from scratch:

- the app image, with `command: ["/app/src/manage.py"]` and `args: [shell, -c, ...]`;
- envFrom the Secret and ConfigMap `<app>`;
- the container securityContext only (no pod securityContext), plus the nodeSelector;
- SA `podiumd`;
- `restartPolicy: OnFailure`, with backoffLimit and activeDeadlineSeconds;
- no probes or ports;
- an emptyDir on `/tmp`;
- the openformulieren Job re-mounts `extraVolumes`, because `EXTRA_VERIFY_CERTS` is opened at startup;
- labels are podiumd selectorLabels plus `app.kubernetes.io/component`;
- the Job name includes a template checksum, and the Job is not a Helm hook.

## Image layout & management commands

### Layout (Dockerfile at each tag)

| Component          | Image                                     | User                | DJANGO_SETTINGS_MODULE                                           | Root scripts                                                                                 | Notes                                                              |
| ------------------ | ----------------------------------------- | ------------------- | ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Open Zaak          | `openzaak/open-zaak:1.29.3`               | openzaak 1000:1000  | openzaak.conf.docker                                             | start, wait_for_db, celery_worker/flower/beat, setup_configuration, load_fixtures, dump_data | `warm_cache` runs at build time (`/app/cache`); creates `/app/tmp` |
| Open Notificaties  | `openzaak/open-notificaties:1.17.0`       | opennotificaties    | nrc.conf.docker                                                  | + celery_worker_liveness_probe                                                               |                                                                    |
| Open Object        | `maykinmedia/open-object:4.3.0`           | user                | objects.conf.docker                                              | dump_data, liveness probe; no beat script                                                    |                                                                    |
| Open Forms         | `openformulieren/open-forms:4.0.2`        | maykin              | openforms.conf.docker                                            | + dump_configuration; `/app/bin/report_*.py`                                                 | `PYTHONOPTIMIZE=1`; VOLUMEs at l.124                               |
| Open Klant         | `maykinmedia/open-klant:2.15.0`           | openklant 1000:1000 | openklant.conf.docker                                            | upgrade_check_version, dump_data; worker and flower scripts only                             |                                                                    |
| Open Inwoner       | `maykinmedia/open-inwoner:2.4.7`          | maykin              | open_inwoner.conf.docker                                         | worker, beat and monitor scripts; no flower                                                  | python:3.13 base                                                   |
| Open Archiefbeheer | `maykinmedia/open-archiefbeheer:2.0.0`    | maykin              | openarchiefbeheer.conf.${DJANGO_SETTINGS} (ARG default `docker`) | **no `/wait_for_db.sh`**; `/replace-envvars.sh`                                              | source at `backend/src` → `/app/src`                               |
| Open Beheer        | `maykinmedia/open-beheer:0.9.1`           | maykin              | openbeheer.conf.${DJANGO_SETTINGS}                               | **only `/start.sh`**                                                                         | source at `backend/src` → `/app/src`                               |
| Open VTB           | `maykinmedia/open-vtb:0.2.0`              | maykin 1000:1000    | openvtb.conf.docker                                              | wait_for_db plus celery scripts                                                              |                                                                    |
| Referentielijsten  | `maykinmedia/referentielijsten-api:0.7.5` | maykin              | referentielijsten.conf.docker                                    | wait_for_db, load_fixtures, setup_configuration; no celery                                   |                                                                    |

Source: `Dockerfile` and `bin/` at each tag (e.g. https://github.com/open-zaak/open-zaak/blob/1.29.3/Dockerfile L64-130).

- **manage.py.** Every `src/manage.py` starts with `#!/usr/bin/env python` and has git mode 100755. The charts and podiumd call `/app/src/manage.py` directly (MK(openzaak-1.14.2)/templates/job-config.yaml).
- **Logging.** `LOG_STDOUT` defaults to True in open-api-framework. OF, OIP, OAB and OB `conf/docker.py` call `setdefault('LOG_STDOUT','yes')`. So every image logs to stdout.

### Start scripts

Every `/start.sh` waits for the DB and runs `migrate`:

| Component          | How it waits             | Extra steps                                                                                                                         |
| ------------------ | ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| Open Zaak          | `wait_for_db.sh`         | `check` runs before the wait; after migrate, `load_fixtures` and `createinitialsuperuser` (if `OPENZAAK_SUPERUSER_USERNAME` is set) |
| Open Notificaties  | `wait_for_db.sh`         | fixtures; superuser if set                                                                                                          |
| Open Object        | `wait_for_db.sh`         | fixtures; superuser if set                                                                                                          |
| Open Forms         | `wait_for_db.sh`         | copies static files to `$STATIC_ROOT_VOLUME`                                                                                        |
| Open Inwoner       | `wait_for_db.sh`         | `migrate --skip-checks`, `check`, `add_missing_templates`, static copy                                                              |
| Referentielijsten  | `wait_for_db.sh`         | `load_fixtures`                                                                                                                     |
| Open Klant         | inline `pg_isready` loop | none                                                                                                                                |
| Open Archiefbeheer | inline `pg_isready` loop | `loaddata default_admin_index`, `replace-envvars`                                                                                   |
| Open Beheer        | inline `pg_isready` loop | none                                                                                                                                |
| Open VTB           | inline `pg_isready` loop | static copy                                                                                                                         |

Upstream scripts run migrate with `OTEL_SDK_DISABLED=True`.

### Management commands relevant to the catalogue (verified at the tags read)

Classes: U = useful, R = read-only, D = dangerous.

| Component                                                  | Command                                                                                                                                                               | Class                  | Notes                                                                                                                                   |
| ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| OZ                                                         | `send_test_notification`                                                                                                                                              | U (writes)             | Registers kanaal `test` in ON, then POSTs a notification                                                                                |
| OZ                                                         | `warm_cache`                                                                                                                                                          | U                      |                                                                                                                                         |
| OZ                                                         | `check_zaak_eigenschappen`                                                                                                                                            | R                      |                                                                                                                                         |
| OZ                                                         | `detect_duplicate_eio [--noinput]`                                                                                                                                    | D                      | Without `--noinput` it calls `input()`, which fails without a TTY                                                                       |
| OZ                                                         | `delete_empty_eioc`, `sync_autorisaties`, `migrate_vestigingen_to_nnps`, `import`, `generate_data`, `createinitialsuperuser`                                          | D                      |                                                                                                                                         |
| ON                                                         | `clean_old_notifications`                                                                                                                                             | D                      | Deletes Notificatie and CloudEvent rows older than `NOTIFICATION_NUMBER_OF_DAYS_RETAINED`. No CronJob runs this by default              |
| OO                                                         | `import_objecttypes <service_slug>`                                                                                                                                   | U (writes, atomic)     | Requires Objecttypes API 2.2.2 or later                                                                                                 |
| OO                                                         | `check_for_external_objecttypes`                                                                                                                                      | R                      | Raises CommandError listing the UUIDs that are not imported                                                                             |
| OO                                                         | `generate_token`                                                                                                                                                      | D                      | **Prints the token to stdout, so it ends up in the Job logs**                                                                           |
| OF                                                         | `register_submission <id>`                                                                                                                                            | U                      |                                                                                                                                         |
| OF                                                         | `register_submission --force`                                                                                                                                         | D                      | Resets status, attempts and result first                                                                                                |
| OF                                                         | `check_legacy_catalogi_api_urls`, `report_unauthenticated_submissions`, `checkpaymentemaildupes`, `check_admin_index`, `list_prefill_plugins`, `dmn_list_definitions` | R                      |                                                                                                                                         |
| OF                                                         | `disable_demo_plugins`                                                                                                                                                | D                      | Deletes all FlagState rows **and** resets `GlobalConfiguration.plugin_configuration` to `{}`                                            |
| OF                                                         | `delete_export_files`                                                                                                                                                 | D                      |                                                                                                                                         |
| OK                                                         | `migrate_to_v2`, `migrate_to_v2_phonenumbers`                                                                                                                         | D                      |                                                                                                                                         |
| OIP                                                        | `clear_cache [--alias]`                                                                                                                                               | U                      | Without `--alias` only the **default** cache is cleared                                                                                 |
| OIP                                                        | `zgw_import_data`, `process_feed_updates`, `send_failed_mail_digest`                                                                                                  | U                      |                                                                                                                                         |
| OIP                                                        | `find_modified_mail_templates`                                                                                                                                        | R                      |                                                                                                                                         |
| OIP                                                        | `config_checks`                                                                                                                                                       | R?                     | `--checks-collector` is required, no non-test collector exists, and the only registered check is interactive. **UNVERIFIED usefulness** |
| OIP                                                        | `prune_notification_records`, `delete_invitations`, CMS4 commands (`migration_preparation` drops tables)                                                              | D                      |                                                                                                                                         |
| OAB                                                        | `resync_zaken`, `cache_zaken`                                                                                                                                         | U                      |                                                                                                                                         |
| OAB                                                        | `create_demo_data`                                                                                                                                                    | D                      |                                                                                                                                         |
| OB                                                         | `health_checks [--with-traceback]`                                                                                                                                    | R                      |                                                                                                                                         |
| all                                                        | `setup_configuration --yaml-file X [--validate-only]`                                                                                                                 | —                      | django-setup-configuration 0.11.0 (ON 0.13.0, OIP 0.12.0)                                                                               |
| maykin_common apps (OZ, ON, OO, OF, OK, OAB, OB, OVTB, RL) | `clear_cache [--alias]`                                                                                                                                               | U                      | Default cache only                                                                                                                      |
| ON, OO, OF, OIP, OVTB                                      | `health_check` (django-health-check through maykin_common)                                                                                                            | not a Check            | **The checks write to the DB.** Not installed in OAB                                                                                    |
| notifications apps                                         | `register_kanalen`                                                                                                                                                    | U                      |                                                                                                                                         |
| all                                                        | `axes_*`                                                                                                                                                              | U/D                    | The available set depends on the axes version (5.25.0 in OIP to 8.3.1 in OF)                                                            |
| OF, OIP, OAB                                               | `prune_timeline_logs`                                                                                                                                                 | D                      |                                                                                                                                         |
| apps with log_outgoing_requests (not OAB/OB)               | `prune_outgoing_request_logs`                                                                                                                                         | D                      |                                                                                                                                         |
| OIP                                                        | `search_index`                                                                                                                                                        | U / D (`--rebuild -f`) |                                                                                                                                         |

Library versions differ per Component (from `requirements/base.txt`):

- open-api-framework: OZ 0.14.0; ON, OO, OVTB, RL 0.16.0; OK 0.13.4.
- notifications-api-common: OZ, OK 0.10.1; ON, OO, OVTB, RL 0.13.1; OIP 0.2.2.

## External URLs

### Where public hosts live

- **HTTPRoutes.** Public routing uses Gateway API `HTTPRoute` objects named `hr-<app>-nginx`, on Gateway `public-gateway` (gatewayClass `nginx`, NGINX Gateway Fabric) in namespace **`ingress-basic`**. ADO `ExternalsPodiumD` creates them on the deploy side. Source: HC/docs/apps/openzaak/openzaak-BASICS.md l.81-82, 172-173; HC/docs/apps/_APP-DOCS-PATTERN.md l.63.
- **No chart routes.** The chart has no HTTPRoute templates, and the subchart `ingress.enabled` defaults are false. The only chart-rendered Ingress is HC/templates/frankgateway-dashboard-ingress.yaml (optional).
- **TLS edge.** TLS may terminate at an Azure Application Gateway in front. cert-manager issues certificates once the DNS CNAME resolves (HC/docs/_UPGRADE_PATHS/4.6.6-to-4.7.3-upgrade.md l.323).
- **Configuration data.** OIDC discovery, zgw_consumers api_roots, sites and Notificaties callback URLs are in ConfigMap `<fullname>-configuration`, key `configuration.yaml` (MK(openzaak-1.14.2)/templates/configuration-data.yaml l.5, 9).

### Platform URL values

| Helm value (HC/values.yaml)                                                    | Rendered into                                                                                                                          | Source                                                                                                                                                                                         |
| ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `keycloak.config.adminFrontendUrl` (l.64)                                      | Keycloak CR hostname fallback; master realm frontendUrl                                                                                | keycloak-cr.yaml l.19-20; keycloak-master-realm-config.yaml l.13                                                                                                                               |
| `keycloak.hostname.hostname`/`.admin` (l.145-146, `""`)                        | Keycloak CR via `coalesce`                                                                                                             | If empty on a fresh install, discovery serves admin-host endpoints until the realm import sets frontendUrl, and logins fail with "Restart login cookie not found" (keycloak-BASICS.md l.85-92) |
| `keycloak.config.realmFrontendUrl` (l.104)                                     | podiumd realm `frontendUrl`                                                                                                            | keycloak-podiumd-realm-config.yaml l.87. Issuer derivation is standard Keycloak behaviour, not read from source                                                                                |
| `<app>.configuration.oidcUrl` (all default `""`)                               | Keycloak client `redirectUris`/`webOrigins` = `<oidcUrl trimSuffix "/">/*`. Render fails on empty or example.nl for enabled Components | keycloak-podiumd-realm-config.yaml l.27-62 (guard), l.251-254                                                                                                                                  |
| `openzaak.configuration.oidcUrl`; `objecten.configuration.oidcUrl` + `/api/v2` | `OPENZAAK_URL` / `OBJECTTYPES_URL`, **not trimmed**                                                                                    | create-required-catalogi.yaml l.30; create-required-objecttypen.yaml l.41                                                                                                                      |
| `keycloak-operator.jobs.keycloakUrl` (l.438)                                   | realm-import Jobs, default `http://keycloak-service:8080`                                                                              | keycloak-import-podiumd-realm-job.yaml l.115                                                                                                                                                   |

### Per-Component URL settings

| Component          | Key settings                                                                                                                                                 | Pitfalls                                                                                                                                    | Source                                                                                                                                    |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| All Maykin apps    | `ALLOWED_HOSTS = "<fullname>,<fullname>.<ns>,<settings.allowedHosts>"`; podiumd default `.svc.cluster.local`                                                 | The public host is absent unless the environment adds it                                                                                    | HC/values.yaml l.853, 1125, 1380, 1653, 1807, 2119, 2404, 2651, 2802, 2969; MK configmap.yaml                                             |
| Open Zaak          | `USE_X_FORWARDED_HOST` True; `IS_HTTPS`; `SITE_DOMAIN` (default `""`)                                                                                        |                                                                                                                                             | MK(openzaak-1.14.2)/templates/configmap.yaml l.10, 16, 80, 126                                                                            |
| Objecten           | `SITE_DOMAIN` is required (`objecten.settings.siteDomain`)                                                                                                   | Render fails while it contains example.nl                                                                                                   | MK(openobject-1.2.0) configmap l.130; HC/templates/validations.yaml l.79-84                                                               |
| Open Inwoner       | allowedHosts comes **first**; `BASE_URL = https://ALLOWED_HOSTS[0]`; nginx `X-Forwarded-Host $server_name` (the first entry)                                 | With the default, BASE_URL becomes `https://.svc.cluster.local`. A routed host missing from ALLOWED_HOSTS gives a **504 after 60 s** on NGF | MK(openinwoner-2.6.0) configmap l.10, configmap-nginx l.11, 24; open-inwoner@2639f95 conf/base.py l.1924-1927; openinwoner-BASICS.md l.42 |
| Open Archiefbeheer | `IS_HTTPS` renders **"False"** (isHttps undefined); `FRONTEND_URL`, `CSRF_TRUSTED_ORIGINS`, CORS                                                             |                                                                                                                                             | MK(openarchiefbeheer-2.1.0) configmap l.39, 91, 97                                                                                        |
| Open Forms         | `BASE_URL` ← `settings.baseUrl` (podiumd does not set it)                                                                                                    | The effect of an empty value is UNVERIFIED                                                                                                  | MK(openforms-1.13.0) configmap l.10                                                                                                       |
| Open Beheer        | `MYKN_API_URL` and `CSRF_TRUSTED_ORIGINS` = `https://<apiDomain>` (default `""`)                                                                             | An empty value renders `https://`                                                                                                           | MK(openbeheer-0.1.3) configmap l.16, 18; HC/values.yaml l.2805                                                                            |
| Open VTB           | `USE_X_FORWARDED_HOST` is hardcoded True                                                                                                                     | podiumd's `useXForwardedHost: false` is ignored                                                                                             | MK(openvtb-0.2.0) configmap l.10                                                                                                          |
| ZAC                | `AUTH_SERVER` (required, must be public), `CONTEXT_URL` (required), `AUTH_REALM`; `zgwApis.urlExtern` is not referenced by any template                      |                                                                                                                                             | ZAC/templates/config.yaml l.11-14, 49                                                                                                     |
| KISS               | `OIDC_AUTHORITY`; adapter `SMOELENBOEK_OBJECT_TYPE_URL` ← `baseUrlExtern`                                                                                    | An empty value renders the relative path `/api/v2/objecttypes/<uuid>`                                                                       | kiss-chart 3.2.0 configmap.yaml l.117; HC/templates/adapter-config.yaml l.12-15                                                           |
| ITA                | `OIDC_AUTHORITY` (public realm), `Ita__BaseUrl`, `AllowedHosts "*"`                                                                                          |                                                                                                                                             | internetaakafhandeling 3.3.4 config.yaml l.9, 19, 48                                                                                      |
| PABC               | `Oidc__Authority` (docs recommend in-cluster `http://keycloak-service:8080/realms/podiumd` with `requireHttps: false`)                                       | Exempt from the public-host comparison                                                                                                      | pabc 2.1.0 configmap.yaml l.19, 25; keycloak-BASICS.md l.178-183                                                                          |
| open-api-framework | `IS_HTTPS` drives secure cookies, HSTS and `AXES_BEHIND_REVERSE_PROXY`; the `CSRF_TRUSTED_ORIGINS` default is derived from CORS **with the scheme stripped** |                                                                                                                                             | open-api-framework@8e4b353 conf/base.py l.1206, 1295-1302                                                                                 |

**Corrections and drift:**

- The APISIX admin-UI Ingress described in HC/docs/apps/apisix/apisix-BASICS.md does **not** exist in 4.10.0. This is doc drift.
- The OMC, office add-in and Zaakbrug URL env names are UNVERIFIED (subcharts not opened).

## Component connectivity

### Key facts

- **Inter-Maykin edges are runtime-only.** They are zgw-consumers `Service` rows written by the setup_configuration Job:
  - The Job runs `/app/src/manage.py setup_configuration --yaml-file /app/configuration/configuration.yaml`.
  - It envFroms the main Secret, `<fullname>-config-secrets` and ConfigMap `<fullname>`.
  - `<fullname>-configuration` is mounted at `/app/configuration`.
  - Source: MK(openzaak-1.14.2)/templates/job-config.yaml.
  - The ConfigMap gives the **desired** state only. Admins can edit Services in the Django admin. The podiumd default is `data: ""`, and the commented examples use public hostnames.
- **Ports** (HC/docs/misc/network-policy-analysis.md):
  - Django pods: 8000 behind Service port 80.
  - `*-nginx`: 8080 behind 80, **except openklant-nginx, which listens on 8000** (MK(openklant-1.11.0)/templates/service.yaml).
  - zac-nginx 8080/80; zac admin 9990; pabc, ita-web and adapter 8080/80; Solr 8983; office-converter 3000.
- **Probe paths** all send `Host: <fullname>`:
  - `/admin/`: openzaak, objecten, openforms, openbeheer, openvtb.
  - `/`: opennotificaties, referentielijsten, openklant, openarchiefbeheer.
  - `/_healthz/livez/` and `/_healthz/readyz/`: openinwoner.
  - nginx `/_health/` is a static 200 from nginx and does not prove Django is reachable (MK(openzaak-1.14.2)/templates/configmap-nginx.yaml L69-72).
- **Service names** come from `fullnameOverride`, and QA rigs use `notificaties` (HC/values.yaml L960-964). Resolve names from live objects.

### Infrastructure edges (visible from env)

| From             | To               | Setting                                                                                        | Target                                                                                                                                                         | Probe                                 | Source                                                                                              |
| ---------------- | ---------------- | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Every Maykin app | Redis HA         | `CACHE_*`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` (ON also has a publish broker on DB 6) | `redis-ha-master:6379`. Cache/Celery DBs: OZ 4/5, ON 3/6, OO 1/2, OK 7/8, OF 9/10, OIP 11/12, OAB 13/14, RL 15, OB 17, OVTB 19/20. **No auth, no TLS** (NW-04) | TCP + PING                            | HC/docs/apps/redis/redis-ha-databases.md                                                            |
| Every Maykin app | PostgreSQL       | `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`; `PGSSLMODE=require`                                   | external:5432                                                                                                                                                  | TCP                                   | HC/values.yaml L852                                                                                 |
| Every Maykin app | SMTP             | `EMAIL_HOST`/`EMAIL_PORT` (587, TLS)                                                           | external                                                                                                                                                       | TCP + EHLO                            |                                                                                                     |
| openinwoner      | Elasticsearch    | `ES_HOST=http://<eck fullnameOverride>-es-http:9200`                                           | `openinwoner-elasticsearch-es-http:9200`                                                                                                                       | `/_cluster/health`                    | MK(openinwoner-2.6.0) configmap L11-18                                                              |
| KISS             | Elasticsearch    | `ELASTIC_BASE_URL`, user `elastic`                                                             | `kiss-es-http:9200`, HTTPS with self-signed cert                                                                                                               | `/_cluster/health`                    | elastic-BASICS.md L94-97                                                                            |
| OF / OIP         | ClamAV           | `GlobalConfiguration` / `SiteConfiguration`, written by umbrella Jobs                          | `clamav:3310`                                                                                                                                                  | clamd PING                            | HC/templates/openformulieren-configure-clamav.yaml L48-74; openinwoner-configure-clamav.yaml L53-68 |
| zac              | Solr             | `SOLR_URL`, default `http://<fullname trunc25>-solr-solrcloud-common`                          | `zac-solr-solrcloud-common:80`                                                                                                                                 | `/solr/admin/collections?action=LIST` | ZAC config.yaml L100-102                                                                            |
| zac              | office-converter | `OFFICE_CONVERTER_CLIENT_MP_REST_URL`                                                          | `zac-office-converter:80`                                                                                                                                      | UNVERIFIED (`/health` assumed)        |                                                                                                     |
| Most apps        | Keycloak         | public `oidcUrl` / discovery endpoint                                                          | public URL                                                                                                                                                     | `.well-known/openid-configuration`    | network-policy-analysis.md                                                                          |

### Application edges visible from env (no DB access needed)

| From                   | Settings                                                                                                                                                                                                                                                                            | Targets                            | Source                                                 |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------ |
| ZAC                    | `ZGW_API_CLIENT_MP_REST_URL` (umbrella `http://open-zaak.internal`), `OBJECTS_API_CLIENT_MP_REST_URL`, `KLANTINTERACTIES_API_CLIENT_MP_REST_URL`, `PABC_API_CLIENT_MP_REST_URL`, `BAG/BRP/KVK_API_CLIENT_MP_REST_URL`, `AUTH_SERVER`, `OPA_API_CLIENT_MP_REST_URL` (localhost:8181) | OZ, OO, OK, PABC, external sources | ZAC/templates/config.yaml, secret.yaml                 |
| KISS                   | `REGISTERS__<i>__{KLANTINTERACTIE,ZAAKSYSTEEM_*}_BASE_URL`; Objecten `*_BASE_URL`; `PABC_BASE_URL`; `HAAL_CENTRAAL_BASE_URL`, `KVK_BASE_URL`                                                                                                                                        | OK, OZ, OO, PABC                   | kiss-chart 3.2.0 configmap.yaml L160-216               |
| KISS adapter           | `SMOELENBOEK_BASE_URL` (default `http://objecten.<ns>.svc.cluster.local`), `ESUITE_BASE_URL`                                                                                                                                                                                        | OO, e-Suite                        | HC/templates/adapter-config.yaml                       |
| ITA (web + 2 CronJobs) | `OpenKlantApi__BaseUrl`, `ObjectApi__BaseUrl`, `ZaakSysteem__BaseUrl`; health `/healthz`                                                                                                                                                                                            | OK, OO, OZ                         | ITA 3.3.4 config.yaml                                  |
| PABC                   | `ZgwZaakregister__CatalogiBaseUrl` (disabled by default); `/alive`, `/health`                                                                                                                                                                                                       | OZ Catalogi                        | pabc 2.1.0 configmap.yaml L36                          |
| office add-in backend  | `API_BASE_URL`, `JWT_SECRET` as **literal env in the Deployment spec**                                                                                                                                                                                                              | OZ                                 | zgw-office-addin 0.0.93 backend-deployment.yaml L46-49 |
| OMC (disabled)         | `ZGW_ENDPOINT_*`, `NOTIFY_API_BASEURL`                                                                                                                                                                                                                                              | ZGW apps                           | notifynl-omc-nodep 0.17.4                              |

### Runtime edges (desired state parsable from `<fullname>-configuration`)

- OZ → ON: notifications-api. The example uses a Token header, while ON's example registers the same secret as a ZGW JWT, so which auth method works is UNVERIFIED.
- ON → OZ Autorisaties: `client_id open-notificaties`.
- OO → ON.
- OF → OO, OZ, OK. The OK Service comes from setup_configuration. The umbrella Job only creates the `CustomerInteractionsAPIGroupConfig`.
- OIP → OZ, and OIP → OK through example api_root `/klanten/api/v1/`. The probe should follow the configured api_root.
- OAB → OZ, Selectielijst, OO, OK.
- OB → OO, OZ, Selectielijst.
- ON-worker → subscriber callbacks (DB only).
- **Invisible without DB/API access:** abonnement callbacks, Services edited in the admin, Open Forms prefill config, Frank!Gateway routes.
- ZAC → ON: no outbound URL env. This edge is UNVERIFIED.

## Shared credential pairs

### Wiring

- **Config Secret.** `<fullname>-config-secrets` is rendered only if `global.configuration.enabled` and `configuration.enabled` are both true.
  - It is skipped when `existingConfigurationSecrets` is set. openvtb uses the singular `<fullname>-config-secret`, and openvtb and openbeheer use the value key `existingConfigurationSecret`.
  - Source: MK(openzaak-1.14.2)/templates/configuration-secrets.yaml; MK(openvtb-0.2.0)/templates/configuration-secrets.yaml l.5.
- **Running pods do not read config-secrets.** The only exception is the openklant init container, which is opt-in and disabled. So a green comparison means "provisioned consistently", not "effective in the DB".
- **4.10.0 defaults.** `configuration.secrets` is `keycloak_client_secret: ""` everywhere. openbeheer also has `openzaak_openbeheer_secret` and `objecttypen_openbeheer_token` (HC/values.yaml l.2694-2697). All other pairs exist only as commented examples.
- **Prefixed header values.** Values with a prefix (`Token <x>`) use inline `REP_..._REP` tokens, so the plaintext ends up in ConfigMap `<comp>-configuration` (HC/values.yaml l.2689-2693).
  - The commented `header_value: Token {value_from: ...}` examples (l.720, 1264, 1970) are **invalid YAML**.
- **Keycloak realm secret.** Secret `keycloak-podiumd-realm-secrets` is built by `podiumd.keycloak.realmSecretsData` (HC/templates/_helpers.tpl l.948).
  - `realmSecret` (l.916) takes the configured value, else the value from a lookup of the existing Secret, else `randAlphaNum 32`.
  - monitoring, datamigratie and zaakbrug are never generated, so they can be empty.
  - validations.yaml l.3-27 checks only monitoring, datamigratie, zaakbrug, kiss, zac, ita and pabc.

### Comparable pairs (class K: both sides in Kubernetes)

| #     | Pair                               | Side A                                                                                                            | Side B                                                                                                                                                    | Source                                                        |
| ----- | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| 1-10  | Maykin Component ↔ Keycloak client | `<comp>-config-secrets[keycloak_client_secret]` (openvtb: `openvtb-config-secret`)                                | `keycloak-podiumd-realm-secrets[<comp>-oidc-secret]`. The OAB clientId is `abc` but its key is `openarchiefbeheer-oidc-secret`. openvtb only when enabled | HC/values.yaml 819-2880; realm-config 242-722                 |
| 12    | KISS ↔ `kiss`                      | `contact[OIDC_CLIENT_SECRET]` (only if non-empty)                                                                 | `[kiss-oidc-secret]`                                                                                                                                      | kiss-chart secret.yaml 42-43                                  |
| 13    | ZAC ↔ `zac.auth.clientId`          | `zac[AUTH_SECRET]`                                                                                                | `[zac-auth-secret]`                                                                                                                                       | ZAC secret.yaml l.8                                           |
| 14    | ZAC admin client                   | `zac[KEYCLOAK_ADMIN_CLIENT_SECRET]`                                                                               | `[zac-keycloak-admin-secret]`                                                                                                                             | ZAC secret.yaml l.14                                          |
| 15    | ITA ↔ `ita`                        | `ita-secrets[OIDC_CLIENT_SECRET]`                                                                                 | `[ita-oidc-secret]`                                                                                                                                       | ITA secrets.yaml 17-20                                        |
| 16-17 | PABC OIDC / keycloakAdmin          | `pabc[Oidc__ClientSecret]`, `pabc[KeycloakAdmin__ClientSecret]` (the Secret is absent if `existingSecret` is set) | `[pabc-oidc-secret]`, `[pabc-keycloak-admin-secret]`                                                                                                      | pabc secret.yaml 14-17                                        |
| 23    | OZ → ON                            | `openzaak-config-secrets[openzaak_opennotificaties_secret]`                                                       | `opennotificaties-config-secrets[same]`. Used as a Token on one side and a JWT on the other, so equal values do not prove the edge works                  |                                                               |
| 24    | ON → OZ Autorisaties               | `opennotificaties-config-secrets[opennotificaties_autorisatie_api_secret]`                                        | `openzaak-config-secrets[same]` (l.823)                                                                                                                   |                                                               |
| 26    | OF → OZ                            | `openformulieren-config-secrets[openzaak_openformulieren_secret]`                                                 | `openzaak-config-secrets[openzaak_openforms_secret]` (**different key name**)                                                                             | values 770/821 vs 1978-1994                                   |
| 27    | OIP → OZ                           | `openinwoner-config-secrets[openzaak_openinwoner_secret]`                                                         | `openzaak-config-secrets[openzaak_openinwoner_secret]` (listed in secrets, not in the credentials items; whether it is effective is unclear)              |                                                               |
| 28    | OB → OZ                            | `openbeheer-config-secrets[openzaak_openbeheer_secret]`                                                           | `openzaak-config-secrets[same]`                                                                                                                           |                                                               |
| 29    | PABC → OZ                          | `pabc[ZgwZaakregister__ClientSecret]`                                                                             | `openzaak-config-secrets[openzaak_pabc_secret]` (values l.826 comment)                                                                                    |                                                               |
| 40/43 | OF/OB → Objecten tokens            | `openformulieren_objecten_token`, `objecttypen_openbeheer_token`                                                  | objecten-config-secrets                                                                                                                                   | values 1276-1308                                              |
| 52-53 | ZAC/KISS → PABC                    | `zac[PABC_API_KEY]`, `contact[PABC_API_KEY]`                                                                      | `pabc[API_KEY__<n>]` (**membership**, not equality)                                                                                                       | ZAC secret.yaml 21; pabc secret.yaml 11-12                    |
| 54    | KISS → adapter                     | `contact[REGISTERS__<i>__*_SECRET / MEDEWERKER_OBJECTEN_CLIENT_SECRET]`                                           | `adapter-secret[CLIENTS__0__SECRET]` (pairing inferred)                                                                                                   | HC/templates/adapter-secret.yaml                              |
| 56    | KISS ↔ ECK ES                      | `contact[ELASTIC_PASSWORD]`                                                                                       | `kiss-es-elastic-user[elastic]` (ECK convention; name **UNVERIFIED** in podiumd source)                                                                   | kiss-chart secret.yaml 12-14; HC/templates/kiss-eck.yaml l.84 |

### Not comparable from Secrets (class A: one side only in a DB)

- ZAC `ZGW_API_SECRET`, KISS `REGISTERS__*__ZAAKSYSTEEM_API_KEY`, ITA `ZaakSysteem__Key`, OAB `oab_openzaak_secret`, create-required-catalogi, Zaakbrug, office add-in and OMC toward Open Zaak. The openzaak `vng_api_common_credentials` example lists only open-formulieren, openbeheer and pabc (HC/values.yaml L766-772).
- ZAC `OPEN_NOTIFICATIONS_API_SECRET_KEY` vs the ON abonnement auth.
- The keycloak-operator client and the bootstrap admin (Keycloak DB).

### Single-source (not pairs)

- OpenBao OIDC secret.
- Frank!Gateway dashboard secret.
- `create-required-objecttypen` token.
- The ZAC office-converter credentials (same `zac` keys).
- `ZAC_INTERNAL_ENDPOINTS_API_KEY`.
- The openbao DB password.
- **Redis has no auth**, so there is nothing to compare.

## Implications for the design

### Script Catalogue entries

- **Command form.** Use `python /app/src/manage.py <cmd>`, with an absolute path. The agreed `python src/manage.py` also works because `WORKDIR /app` is set in all 10 images, but only if `workingDir` is not overridden. Set `workingDir: /app` explicitly or use the absolute path.
- **Applicability.** Mark each entry with its Component(s). Hide entries for Components without a web Deployment (OAB, RL, OB and OVTB are off by default).
- **Initial v1 entries (U):**
  - `clear_cache` (default cache only; document `--alias`);
  - `axes_reset_username <user>`;
  - OZ `send_test_notification` (writes kanaal `test`) and `warm_cache`;
  - `register_kanalen`;
  - OO `import_objecttypes <slug>`;
  - OF `register_submission <id>`;
  - OAB `resync_zaken` / `cache_zaken`;
  - OIP `zgw_import_data`, `search_index --populate`.
- **Dangerous tier** (extra confirmation):
  - data cleanup: `clean_old_notifications`, `delete_empty_eioc`, `detect_duplicate_eio --noinput`, `sync_autorisaties`, `disable_demo_plugins`, `delete_export_files`, `prune_*`, `delete_invitations`;
  - index and data migrations: `search_index --rebuild -f`, `migrate_to_v2*`;
  - forced re-registration: `register_submission --force`.
- **Exclude:**
  - `shell`, `dbshell`, `flush`;
  - `generate_token` (the secret ends up in Job logs);
  - `createinitialsuperuser`, `generate_data`, `create_demo_data`, the CMS4 commands;
  - any command that prompts (e.g. `detect_duplicate_eio` without `--noinput`). Jobs have no TTY.
- **`setup_configuration`: do not offer it as a derived Script in v1.** It needs `<fullname>-config-secrets` envFrom and the `<fullname>-configuration` volume, and the web pod has neither. Re-running the chart's `<name>-config` Job is the better route.
- **`health_check` is not read-only**, because the django-health-check checks write to the DB. Do not use it as a Check.

### Job derivation rules

1. **Source.** The Deployment named `<fullname>`, resolved from live objects because `fullnameOverride` varies. Use the container whose name equals the Chart name or alias (fullname for OAB). Fall back to `containers[0]`. Never use `-nginx`, `-worker` or `-beat`.
2. **Keep:**
   - image, imagePullPolicy, envFrom, env (including OAB `PYTHONPATH` and the `*_PORT` vars);
   - **all** volumes and volumeMounts of the live Deployment (media PVC subPaths, OF `verify-certs` and `openformulieren-configuration`, OAB patches, any extraVolumes);
   - pod and container securityContext, serviceAccountName, nodeSelector, tolerations, affinity, imagePullSecrets, resources.
3. **Override:** command and args (`/start.sh` would migrate and start uwsgi), with workingDir `/app`.
4. **Remove:** all probes, ports and lifecycle.
5. **Init containers:** drop all. There are no required ones (openinwoner `search-index`, and optionally `cms4-migration` and openklant `-config`, are all removable). Optionally prefix the command with `/wait_for_db.sh &&`. This is not available in OAB or OB, so use a `pg_isready` loop or skip it there.
6. **Labels:** replace them all. **Never** keep `app.kubernetes.io/name: <app>`, because it joins the Service endpoints (a pod without a readinessProbe counts as Ready) and the PDB selection (PDBs over pods of a Job make evictions error out). Use a dedicated label, e.g. `app.kubernetes.io/name: podiumd-admin-script` plus `app.kubernetes.io/component: <app>`.
7. **NetworkPolicy:** where policies are enforced (Cilium clusters), the dedicated label must be added to `networkPolicies.protectBackends.extraFrom.redis` (and `.clamav` for OF/OIP Scripts that scan files). The alternative is borrowing `<app>-config`, which is on the Redis allowlist but not the ClamAV one. Document this in install docs as a per-environment values change.
8. **Annotations:** drop `checksum/*`.
9. **Env and volumes:** add `OTEL_SDK_DISABLED=True` (upstream practice for one-off commands). Optionally add an emptyDir on `/tmp`, as Dimpact's precedent Jobs do. Keep `readOnlyRootFilesystem: false`, as in the source.
10. **Job spec:** `restartPolicy: Never`, `backoffLimit: 0`, plus `ttlSecondsAfterFinished` and `activeDeadlineSeconds`. Never/0 is a deliberate design choice; Dimpact's precedent uses OnFailure with retries.

### RBAC resourceNames

Compute the names at install time from release values, because `fullnameOverride` varies.

**Rules that cannot be narrowed by resourceNames.** Kubernetes does not apply resourceNames to `create`, `list` or `watch`:

- `jobs`: create, list, delete in the podiumd namespace;
- `pods`: list, plus `pods/log` get;
- these need label-based discipline instead.

**Rules with resourceNames:**

| Resource                                                    | Verbs | resourceNames                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ----------------------------------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| deployments                                                 | get   | `openzaak`, `opennotificaties`, `objecten`, `openklant`, `openformulieren`, `openinwoner`, and if enabled `openarchiefbeheer`, `referentielijsten`, `openbeheer`, `openvtb`. For status Checks also the `-worker`/`-beat`/`-nginx` variants and `zac`, `contact`, `ita-*`, `pabc`                                                                                                                                                                                                                                                                                                           |
| configmaps                                                  | get   | `<comp>-configuration` (×10), `<comp>` (main ConfigMaps, for URL Checks), `create-required-catalogi-configmap`                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| secrets (compare only)                                      | get   | `keycloak-podiumd-realm-secrets`; `openzaak-config-secrets`, `opennotificaties-config-secrets`, `objecten-config-secrets`, `openklant-config-secrets`, `openformulieren-config-secrets`, `openinwoner-config-secrets`, `openarchiefbeheer-config-secrets`, `referentielijsten-config-secrets`, `openbeheer-config-secrets`, **`openvtb-config-secret`**; `zac`, `contact`, `ita-secrets`, `pabc`, `adapter-secret`; `kiss-es-elastic-user` (name UNVERIFIED). The names change if an environment uses `existingConfigurationSecret(s)`, `configurationSecretsName` or `pabc.existingSecret` |
| httproutes.gateway.networking.k8s.io in **`ingress-basic`** | get   | `hr-<app>-nginx` per Component (the naming convention comes from docs, **UNVERIFIED per environment**). Discovering routes needs `list`, which cannot be name-restricted                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ingresses                                                   | get   | frankgateway dashboard Ingress (optional)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |

- **Deployment specs can contain secrets.** The office add-in Deployment holds `JWT_SECRET` as literal env. Reading Deployment specs must redact env `value` fields in the UI and logs.

### Prioritised v1 Checks (all read-only)

1. **Keycloak client-secret drift** (#1-10, #12-17): compare by hash `keycloak-podiumd-realm-secrets[<comp>-oidc-secret]` with the Component copy. Report "missing/empty" (KISS keys are conditional; monitoring, datamigratie and zaakbrug may be empty) separately from "mismatch".
2. **Public host consistency.** Compare HTTPRoute hostnames in `ingress-basic` (with `objecttypen-nginx` mapped to objecten) against:
   - each Component's `ALLOWED_HOSTS` (the default `.svc.cluster.local` lacks the public host);
   - for OIP, the requirement that `ALLOWED_HOSTS[0]` is the public host (it drives BASE_URL and X-Forwarded-Host);
   - the `oidcUrl` host;
   - Keycloak `hostname.hostname` being non-empty.
3. **Workload health.** Each web, worker and beat Deployment is Available, and no rollout is stuck.
4. **Cross config-secret pairs.** #23, #24, #26 (with key mapping), #27-29, #40, #43. PABC API-key membership #52-53. KISS ↔ ES #56.
5. **Configuration ConfigMap lint.** Check `<comp>-configuration`:
   - `data` is empty or valid YAML (this catches the invalid `Token {value_from...}` form);
   - api_root hosts resolve;
   - untrimmed trailing slashes in `oidcUrl` (`OBJECTTYPES_URL`, `OPENZAAK_URL`).
6. **URL setting lint:**
   - OAB `IS_HTTPS="False"`;
   - OB `MYKN_API_URL`/`CSRF_TRUSTED_ORIGINS` equal to `https://`;
   - KISS `SMOELENBOEK_OBJECT_TYPE_URL` relative;
   - ZAC `AUTH_SERVER` not public;
   - `CSRF_TRUSTED_ORIGINS` without a scheme (a general Django rule; UNVERIFIED in these repos).
7. **Infrastructure reachability** from the admin tool pod:
   - Redis PING (needs an `extraFrom.redis` allowlist where policies are enforced);
   - Postgres TCP;
   - ES `/_cluster/health`;
   - ClamAV PING;
   - Solr;
   - Keycloak `.well-known`.

   Treat any HTTP response from ZGW roots as reachable, because unauthenticated status codes are UNVERIFIED.

8. **TLS certificate expiry and SANs** at the public edge, probed via public DNS and SNI. This may hit the Azure Application Gateway. In-cluster probes may hairpin.
9. **Job-based read-only Checks** (only if the design allows a Check to launch a Job): `migrate --check` (standard Django, unverified per image), OO `check_for_external_objecttypes`, OB `health_checks`, OZ `check_zaak_eigenschappen`, OF `check_legacy_catalogi_api_urls`.
10. **NetworkPolicy awareness (informational).** Report whether `networkPolicies.enabled` is on and whether the cluster enforces policies. This explains why label-dependent Script access behaves differently between environments.

## Still unverified / open

- **Per-environment values.** Hostnames, `REP_*_REP` replacements, overrides of extraVolumes, nodeSelector and tolerations, and whether `networkPolicies.enabled` is on anywhere.
- **Live-cluster sidecar injection** by mutating webhooks outside the chart. Production policy engine ("not checked").
- **Operator-created pod structures:** Keycloak, redis-ha, ECK, SolrCloud. Also the PABC, KISS, ITA and office add-in pod structure.
- **ZAC.** The deployment template at pinned 1.0.355 (OPA sidecar and init-solr: medium confidence, from `main`). Whether ZAC makes outbound calls to ON, and its ON callback path.
- **4.10.1 template changes** in `networkpolicies.yaml`, the Keycloak jobs, `objecttypen-compat-service.yaml` and the new `zac-restart-after-openzaak-config.yaml`. These were not re-read in detail.
- **Media PVC.** The exact accessModes line and CSI driver.
- **Secret names.** ECK Secret `kiss-es-elastic-user`. The OMC, office add-in and Zaakbrug Secret names, keys and URL env vars (subcharts not opened; zaakbrug 2.3.36 in 4.10.1).
- **Keycloak.** Whether keycloak-config-cli overwrites existing client secrets on re-import (drift between the Keycloak DB and `keycloak-podiumd-realm-secrets`). Issuer derivation and `webOrigins` matching for `https://host/*`.
- **Auth details.** How ON validates `object_notificaties_token`. OZ→ON Token vs JWT. OIP→OK zgw vs Token. The ZGW client_id of the office add-in. KISS adapter validation of `CLIENTS__0__SECRET`.
- **Command behaviour:**
  - `migrate --check` in these images;
  - the `config_checks` collectors in OIP;
  - the `generate_notificaties` semantics;
  - django_yubin command names (OF, OIP);
  - the `axes_*` set per version;
  - the `prune_timeline_logs` options;
  - how `/app/bin/report_*.py` in OF is meant to be invoked.
- **Endpoints.** Unauthenticated responses of ZGW API roots and Objecten `/api/v2/`. The Gotenberg health path.
- **Open Forms.** The effect of an empty `BASE_URL`. The DB models for prefill plugin config.
- **Policy.** Whether reading ON abonnementen through the API is acceptable under the rule that Secrets may only be read for comparison (design decision).
- **HTTPRoute naming.** `hr-<app>-nginx` is a documented convention, not chart-rendered. The admin tool's access to `ingress-basic` is an RBAC design decision.
