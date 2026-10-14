"""Describe configured execution without contacting a provider or exposing secrets."""
import os


def catalogue_execution():
    from admaker.photo_worker import photo_worker_configuration
    from admaker.provider_worker import provider_worker_configuration

    modes = {}
    for kind, flag, configure in (("photo", "ENABLE_REAL_PHOTO", photo_worker_configuration),
                                  ("video", "ENABLE_REAL_VEO", provider_worker_configuration)):
        real = os.environ.get(flag) == "true"
        enabled = os.environ.get("ENABLE_LOCAL_FIXTURE_UI") == "true"
        if real:
            try:
                configure()
                enabled = True
            except ValueError:
                enabled = False
        modes[kind] = {"executionMode": "google" if real else "fixture",
                       "generationEnabled": enabled, "requiresAiConsent": real}
    return modes
