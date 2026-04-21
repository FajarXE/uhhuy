import platform
import subprocess
import ctypes
import os

class SleepPreventer:
    def __init__(self):
        self.os_type = platform.system()
        self.mac_process = None

    def keep_awake(self):
        try:
            if self.os_type == 'Windows':
                # ES_CONTINUOUS = 0x80000000, ES_SYSTEM_REQUIRED = 0x00000001
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
            elif self.os_type == 'Darwin':
                if self.mac_process is None:
                    # caffeinate -i prevents idle sleep
                    self.mac_process = subprocess.Popen(['caffeinate', '-i'])
            elif self.os_type == 'Linux':
                # We can leave Linux as no-op or add simple print for now
                pass
        except Exception as e:
            print(f"Error preventing sleep: {e}")

    def allow_sleep(self):
        try:
            if self.os_type == 'Windows':
                # ES_CONTINUOUS = 0x80000000
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            elif self.os_type == 'Darwin':
                if self.mac_process is not None:
                    self.mac_process.terminate()
                    self.mac_process.wait()
                    self.mac_process = None
            elif self.os_type == 'Linux':
                pass
        except Exception as e:
            print(f"Error allowing sleep: {e}")

preventer = SleepPreventer()

def keep_awake():
    preventer.keep_awake()

def allow_sleep():
    preventer.allow_sleep()
