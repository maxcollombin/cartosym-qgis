import pytest

from cartosym_qgis.render import qgis_app


@pytest.fixture(scope="session", autouse=True)
def _qgis():
    with qgis_app():
        yield
