import inspect
from re import L

get_module_name = lambda : next((s.filename for s in inspect.stack() if 'interface.py' in s.filename), None).split('/')[-2]

class ModuleAuthError(Exception):
    def __init__(self):
        super().__init__(f'Invalid login details for the {get_module_name()} module')

class ModuleAPIError(Exception):
    def __init__(self, error_code: int, error_message: str, api_endpoint: str) -> None:
        __class__.__name__ = get_module_name() + 'ModuleAPIError'
        return super().__init__(f'Error {error_code!s}: {error_message} using endpoint {api_endpoint}')

class ModuleGeneralError(Exception):
    def __init__(self, *args, **qwargs) -> None:
        __class__.__name__ = get_module_name() + 'ModuleGeneralError'
        return super().__init__(*args, **qwargs)

class InvalidInput(Exception):
    pass # TODO: fill out with custom message, will not be in error format

class InvalidModuleError(Exception):
    pass # TODO: fill out with custom message, will be in error format

class ModuleDoesNotSupportAbility(Exception):
    pass # TODO: fill out with custom message, will be in error format

class ModuleSettingsNotSet(Exception):
    pass # TODO: will either tell you to add settings for a specific module in simple sessions mode, or the command needed to set a setting in advanced sessions mode

class TagSavingFailure(Exception):
    pass

# Add definitions for AuthenticationError and DownloadError
class AuthenticationError(Exception):
    """Custom exception for authentication failures in modules."""
    pass

class DownloadError(Exception):
    """Base exception for download-related errors"""
    pass

class TrackUnavailableError(DownloadError):
    """Raised when a track is unavailable for download"""
    pass

class ArtworkError(DownloadError):
    """Raised for artwork-related errors"""
    pass