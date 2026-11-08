from importlib.metadata import version

import podiumd_admin


def test_package_exposes_its_installed_version() -> None:
    assert podiumd_admin.__version__ == version("podiumd-admin")
