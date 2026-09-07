import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ecommerce_ai_agent.llm.errors import ModelError
from ecommerce_ai_agent.schemas.error import ErrorBody, ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


class ApplicationError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: list[ErrorDetail] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []


def build_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details or [])
    ).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=payload)


async def validation_exception_handler(
    _request: Request,
    exception: RequestValidationError,
) -> JSONResponse:
    details = [
        ErrorDetail(
            field=".".join(str(part) for part in error["loc"]),
            message=error["msg"],
            type=error["type"],
        )
        for error in exception.errors()
    ]
    return build_error_response(
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        details=details,
    )


async def application_exception_handler(
    _request: Request,
    exception: ApplicationError,
) -> JSONResponse:
    return build_error_response(
        status_code=exception.status_code,
        code=exception.code,
        message=exception.message,
        details=exception.details,
    )


async def http_exception_handler(
    _request: Request,
    exception: StarletteHTTPException,
) -> JSONResponse:
    known_errors = {
        HTTPStatus.NOT_FOUND: ("not_found", "Resource not found"),
        HTTPStatus.METHOD_NOT_ALLOWED: ("method_not_allowed", "Method not allowed"),
    }
    code, message = known_errors.get(
        exception.status_code,
        ("http_error", HTTPStatus(exception.status_code).phrase),
    )
    return build_error_response(
        status_code=exception.status_code,
        code=code,
        message=message,
    )


async def unexpected_exception_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    logger.exception(
        "Unhandled application exception",
        extra={"error_type": type(exception).__name__},
    )
    return build_error_response(
        status_code=500,
        code="internal_server_error",
        message="An unexpected error occurred",
    )


async def model_exception_handler(
    _request: Request,
    exception: ModelError,
) -> JSONResponse:
    return build_error_response(
        status_code=exception.status_code,
        code=exception.code,
        message=exception.public_message,
    )


def register_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(ApplicationError, application_exception_handler)
    application.add_exception_handler(ModelError, model_exception_handler)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(Exception, unexpected_exception_handler)
