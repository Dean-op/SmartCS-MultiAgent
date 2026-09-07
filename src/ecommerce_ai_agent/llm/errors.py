class ModelError(Exception):
    code = "provider_error"
    status_code = 502
    public_message = "The model provider returned an invalid response"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class ModelConfigurationError(ModelError):
    code = "model_not_configured"
    status_code = 503
    public_message = "The model provider is not configured"


class ModelAuthenticationError(ModelError):
    code = "provider_authentication_failed"
    status_code = 502
    public_message = "The model provider rejected its credentials"


class ModelRateLimitError(ModelError):
    code = "provider_rate_limited"
    status_code = 503
    public_message = "The model provider is temporarily rate limited"


class ModelTimeoutError(ModelError):
    code = "provider_timeout"
    status_code = 504
    public_message = "The model provider timed out"


class ModelUnavailableError(ModelError):
    code = "provider_unavailable"
    status_code = 503
    public_message = "The model provider is temporarily unavailable"


class StructuredOutputError(ModelError):
    code = "structured_output_invalid"
    status_code = 502
    public_message = "The model returned invalid structured output"


class ModelProviderError(ModelError):
    pass
