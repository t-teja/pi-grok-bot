from app.config import load_settings


def test_default_model_is_grok_4_6():
    settings = load_settings()
    assert settings.model == "grok-4.6"
    assert "x.ai" in settings.base_url


def test_public_status_has_no_key():
    settings = load_settings()
    pub = settings.as_public_dict()
    blob = str(pub).lower()
    assert "api_key" not in blob
    assert "xai-" not in blob
