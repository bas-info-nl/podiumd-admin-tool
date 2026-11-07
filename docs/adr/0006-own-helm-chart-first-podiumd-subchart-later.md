# Own Helm chart first, PodiumD subchart later

The Admin Tool is released as its own Helm chart, on its own release cycle, while it is changing quickly. The intent is to offer it to Dimpact and have it become an optional PodiumD subchart once it is stable. Until then, the Script Catalogue and the expected-version values for Checks live in the Admin Tool's values, and must be kept in step with the PodiumD release by hand.

Because it is meant for upstream adoption, the tool must follow Dimpact/PodiumD and Common Ground conventions from the start: an open-source license, chart structure and values style matching the PodiumD chart, and configuration only through Helm values.
