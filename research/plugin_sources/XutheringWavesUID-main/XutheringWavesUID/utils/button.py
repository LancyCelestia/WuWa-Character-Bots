from gsuid_core.sv import get_plugin_available_prefix
from gsuid_core.message_models import Button

PREFIX = get_plugin_available_prefix("XutheringWavesUID")


class WavesButton(Button):
    prefix = PREFIX
