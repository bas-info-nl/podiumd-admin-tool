# The Script Catalogue is declared in Helm values with typed parameters and no shell

The Scripts available in an Environment are declared in the Admin Tool's Helm values. Each entry names a Component, the Deployment to copy, a `manage.py` command, and typed parameters (`string` with a pattern, `integer`, `boolean`, `enum`). The tool builds the container `args` as an array, one element per value. It never goes through a shell. Scripts that can't be undone are marked `dangerous` and need typed confirmation.

The available management commands change with each PodiumD release. Declaring them in values lets the catalogue ship and be versioned together with the release, without rebuilding the Admin Tool. Typed parameters with no shell mean that someone with access to the Admin Tool cannot turn a Script into arbitrary command execution. We rejected free-form commands, and catalogues hard-coded in the tool's source.
