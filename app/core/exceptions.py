class AppError(Exception):
    """Base class for application errors that map to a clean HTTP response."""

    status_code = 400

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class OrganizationNotFoundError(AppError):
    status_code = 404


class DocumentNotFoundError(AppError):
    status_code = 404


class InteractionNotFoundError(AppError):
    status_code = 404


class InvalidPdfError(AppError):
    """Raised when an upload fails validation (not a PDF, too large, etc.)."""

    status_code = 422


class PdfProcessingTimeoutError(AppError):
    """Raised when extraction/parsing exceeds the safety time budget."""

    status_code = 422


class NoReadyDocumentsError(AppError):
    """Raised when a query is issued for an org with no successfully ingested documents."""

    status_code = 422
