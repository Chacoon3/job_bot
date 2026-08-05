"""
defines custom exceptions for the job_bot application.
"""


class IncompleteApplicationError(Exception):
    """Raised when the application is incomplete and cannot be submitted."""
