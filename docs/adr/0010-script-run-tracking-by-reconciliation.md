# Script Runs are tracked by reconciling Jobs, with one backend replica in v1

The database is the system of record for Script Runs. A background reconcile loop (a watch plus periodic resync on Jobs labelled `podiumd-admin/script-run`) moves each Script Run's status forward and copies the pod logs into the stored Script Run Output before the Job's TTL removes them. Because of this, a restart of the backend loses no Script Run state. v1 runs a single backend replica, so no leader election is needed. Running more than one replica later would require it.
