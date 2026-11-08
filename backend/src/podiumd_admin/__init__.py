"""PodiumD Admin Tool backend.

The package follows a hexagonal layout (ADR 0009, design D1):

- ``domain``: plain Python domain model and policies; depends on nothing outside it.
- ``application``: use cases that orchestrate the domain through ports.
- ``ports``: ``typing.Protocol`` interfaces the application needs from the outside world.
- ``adapters``: implementations of the ports and the inbound HTTP API.
"""

from importlib.metadata import version

__version__ = version("podiumd-admin")
