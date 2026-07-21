"""Minimal AppConfig stub."""


class AppConfig:
    def __init__(self, **kwargs):
        self.name = kwargs.get("name", "local")
        self.debug = kwargs.get("debug", True)
