from app.services import system_service


class TestGetAppEnvironment:
    def test_returns_the_configured_environment(self):
        # tests/conftest.py sets APP_ENVIRONMENT="test" for the whole suite.
        assert system_service.get_app_environment() == "test"
