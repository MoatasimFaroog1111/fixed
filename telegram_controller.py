"""
Disabled legacy TelegramController.
Do not use getUpdates here.
Use telegram_control.py only.
"""

class TelegramController:
    def __init__(self, *args, **kwargs):
        self.disabled = True

    def start(self):
        return None

    def stop(self):
        return None
