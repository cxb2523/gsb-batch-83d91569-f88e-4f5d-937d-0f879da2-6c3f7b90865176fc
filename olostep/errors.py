"""
Olostep API SDK Exceptions.

This module defines the exception hierarchy for the Olostep API SDK,
providing specific error types for different failure scenarios.

Our exception hierarchy:

* Olostep_BaseError -------------------------------------- <- Catch base class for all errors
  x Olostep_APIConnectionError --------------------------- <- No connection to the API
  x OlostepServerError_BaseError ------------------------- <- Server-issued errors (still detected in client ofc)
    + OlostepServerError_TemporaryIssue
      - OlostepServerError_NetworkBusy
      - OlostepServerError_InternalNetworkIssue
    + OlostepServerError_RequestUnprocessable
      - OlostepServerError_ParserNotFound
      - OlostepServerError_OutOfResources
    + OlostepServerError_BlacklistedDomain
    + OlostepServerError_FeatureApprovalRequired
    + OlostepServerError_AuthFailed
    + OlostepServerError_CreditsExhausted
    + OlostepServerError_InvalidEndpointCalled
    + OlostepServerError_ResourceNotFound
    + OlostepServerError_NoResultInResponse
    + OlostepServerError_UnknownIssue
  x OlostepClientError_BaseError ------------------------- <- Client-issued errors
    + OlostepClientError_RequestValidationFailed
    + OlostepClientError_ResponseValidationFailed
    + OlostepClientError_NoAPIKey
    + OlostepClientError_AsyncContext
    + OlostepClientError_BetaFeatureAccessRequired
    + OlostepClientError_Timeout
"""

import pprint
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from olostep.backend.transport_protocol import RawAPIRequest, RawAPIResponse
else:
    RawAPIRequest = Any
    RawAPIResponse = Any


class Olostep_BaseError(Exception):
    """Base exception for all Olostep SDK errors.

    Never raised directly, only as a base class for other errors.
    Catch this to catch all Olostep SDK errors indiscriminately.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


# pruposefully not a client error because it lives in the transport layer and we dont want it to be caught by the client
class Olostep_APIConnectionError(Olostep_BaseError):
    """Raised when the underlying connection to Olostep API fails either to connect or to get a(ny) response.

    Note: HTTP status errors (4xx, 5xx) are not considered network-level errors
        as they are error messages from the API and defined below as separate errors.
    """

    def __init__(self) -> None:
        exc = sys.exc_info()[1]
        self.original_error = (
            f": [{type(exc).__name__}]" if isinstance(exc, Exception) else ""
        )
        msg = f"Olostep API connection error{self.original_error}"
        super().__init__(msg)


#########################
# Server issued errors
#########################


class OlostepServerError_BaseError(Olostep_BaseError):
    """Base exception for Olostep errors raised by the server.
    Never raised directly, only as a 2nd level base class for other errors.

    Catch this to catch all Olostep SDK errors raised by the server.
    """

    def __init__(self, message: str | None = None) -> None:
        self.message = message or "The API returned an unknown error"
        super().__init__(message)


class OlostepServerError_TemporaryIssue(OlostepServerError_BaseError):
    """Raised when the API encounters a transient (temporary) network error.

    Base class for transient backend errors. You can try again later.
    """

    def __init__(self) -> None:
        super().__init__(
            "The API returned a termporary error. you can try again later."
        )


class OlostepServerError_RequestUnprocessable(OlostepServerError_BaseError):
    """Raised when the API understands your request but deems it to contain invalid or unprocessable instructions.

    Maps to a HTTP 400 (Bad Request) status code OR HTTP 500 (Internal Server Error) status code.
    And HTTP 502 (Bad Gateway) status code on the crawl endpoint.

    This error pattern indicates that the request was malformed in a way that prevented proper processing.
    We handle 400 and 500 as the same error because the API has weak input validation.


    This is checked before an authentication issue.

    """

    def __init__(
        self,
        request: RawAPIRequest,
        response: RawAPIResponse,
    ) -> None:
        self.request = request
        self.response = response

        # Format the request: show URL and json (if present)
        formatted_request = f"Request URL: {request.url}\n"
        request_json = getattr(request, "json", None)
        if request_json:
            formatted_request += f"Request JSON:\n{pprint.pformat(request_json)}\n"

        # Format the response for display
        body = response.body
        if isinstance(body, dict):
            formatted_response = pprint.pformat(body)
        elif isinstance(body, str):
            formatted_response = body
        else:
            formatted_response = repr(body)

        message = (
            f"Invalid request to {request.method} {request.url}: {response.status_code}\n"
            f"{formatted_request}"
            f"Response:\n{formatted_response}"
        )

        super().__init__(message)


class OlostepServerError_ParserNotFound(OlostepServerError_RequestUnprocessable):
    """Raised when the parser is not found."""

    def __init__(self, request=None, response=None) -> None:
        super().__init__(request=request, response=response)


class OlostepServerError_BlacklistedDomain(OlostepServerError_BaseError):
    """Raised when the domain is blacklisted by the API.

    Maps to a HTTP 401 (Unauthorized) status code.

    This error has never been observed in practice but exists according to the API documentation.
    """

    def __init__(self) -> None:
        super().__init__("The domain has been blacklisted by the Olostep API")


class OlostepServerError_FeatureApprovalRequired(OlostepServerError_BaseError):
    """Raised when approval is required for a specific feature.

    Maps to a HTTP 403 (Forbidden) status code.

    This error has never been observed in practice but exists according to the API documentation.
    """

    def __init__(self) -> None:
        super().__init__("Approval is required to use this feature")


class OlostepServerError_AuthFailed(OlostepServerError_BaseError):
    """Raised when API rejects the provided API key.

    Maps to a HTTP 402 (Payment Required) status code.

    If supplied, the message reveals only the last 4 characters of the key, so error
    messages and logs never carry a usable part of it.
    """

    msg_template = "The API rejected your API Key {masked}as invalid"

    def _mask_key(self, key: str | None) -> str:
        if not key:
            return ""
        if len(key) < 12:
            return "[*****] "
        return f"[*****{key[-4:]}] "

    def __init__(
        self,
        api_key: str | None = None,
    ) -> None:
        masked = self._mask_key(api_key)
        message = self.msg_template.format(masked=masked)
        super().__init__(message)


class OlostepServerError_CreditsExhausted(OlostepServerError_BaseError):
    """Raised when the API rejects the request because the credit is exhausted.

    Maps to a HTTP 402 (Payment Required) status code with a message of "Your have consumed all available credits. Please upgrade your plan from the dashboard: https://www.olostep.com/auth/"
    """

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "The API rejected your request because the credit is exhausted"
        )


class OlostepServerError_InvalidEndpointCalled(OlostepServerError_BaseError):
    """Raised when an invalid Method + Endpoint is requested.

    Maps to a HTTP 404 with the title "route not found". Older API versions sent a
    HTTP 403 (Forbidden) status code with a very misleading message of
    'Invalid key=value pair (missing equal-sign) in Authorization header (hashed with SHA-256 and encoded with Base64): [...]'
    and a X-Amzn-ErrorType header of 'IncompleteSignatureException'

    This is typically NOT an authentication issue,
    but rather indicates a problem with the request structure itself.

    Common causes:
    - Incorrect URL format (e.g., using path parameters instead of query parameters)
    - Malformed query parameters
    - Wrong HTTP method

    When this error occurs, check:
    1. URL format and structure
    2. Query parameter formatting
    3. HTTP method

    Example:
        This error commonly occurs when using path parameters for endpoints
        that expect query parameters, such as:
        - Wrong: /retrieve/{retrieve_id}
        - Correct: /retrieve?retrieve_id=...&formats=...
    """

    def __init__(
        self,
        requested_url: str,
        requested_method: str,
        server_response: dict[str, Any] | str | None = None,
    ) -> None:
        self.requested_url = requested_url
        self.requested_method = requested_method
        self.server_response = server_response

        method_path = f"{requested_method.upper()} {requested_url}"
        message = (
            f"An Invalid API Endpoint was requested:\n  Method/Path: {method_path}"
        )
        attachment = ""

        if isinstance(server_response, dict):
            attachment = pprint.pformat(server_response)
        elif isinstance(server_response, str):
            attachment = server_response

        if attachment:
            message = f"{message}\n{attachment}"

        super().__init__(message)


class OlostepServerError_NetworkBusy(OlostepServerError_TemporaryIssue):
    """Raised when the API is busy and cannot process the request.

    The server raises these as HTTP 501 (Not Implemented) status code.
    """

    def __init__(self) -> None:
        super().__init__()


class OlostepServerError_ResourceNotFound(OlostepServerError_BaseError):
    """Raised when the requested resource is not found.

    Maps to a HTTP 404 (Not Found) status code.
    """

    def __init__(self, server_response: str | None = None) -> None:
        self.message = f"The requested ressource was not found by the server.\nServer response: {server_response}"
        super().__init__(self.message)


class OlostepServerError_OutOfResources(OlostepServerError_RequestUnprocessable):
    """Raised when the server has not enough resources to process the request.

    Maps to a HTTP 404 (Not Found) status code with a message of "Not enough resources available for the batch execution."
    """

    def __init__(self, request: RawAPIRequest, response: RawAPIResponse) -> None:
        self.message = f"The API does not have enough ressources to process your request.\nServer response: {response.body}"
        super().__init__(request=request, response=response)


class OlostepServerError_NoResultInResponse(OlostepServerError_BaseError):
    """Raised when the Olostep API fails to return a result due to timeout.

    Maps to a HTTP 504 (Gateway Timeout) status code with HTML response.
    This indicates a true timeout where the server could not process the request
    within the allowed time limit. This error should NOT be retried.
    """

    pass


class OlostepServerError_InternalNetworkIssue(OlostepServerError_TemporaryIssue):
    """Raised when the Olostep API encounters a transient network error.

    Maps to a HTTP 504 (Gateway Timeout) status code with JSON response containing
    "Network error communicating with endpoint" message.
    This indicates a temporary network issue that may be resolved by retrying.
    """

    pass


class OlostepServerError_UnknownIssue(OlostepServerError_BaseError):
    """Raised when the the SKD could not match any other error to a given API response."""

    def __init__(
        self, status_code: int, server_response: dict[str, Any] | str | None = None
    ) -> None:
        self.message = f"[HTTP: {status_code}] The Olostep API return an unknown error"

        self.status_code = status_code
        self.response_data = server_response

        attachment = ""

        if isinstance(server_response, dict):
            attachment = pprint.pformat(server_response)

        elif isinstance(server_response, str):
            attachment = server_response

        if attachment:
            self.message = f"{self.message}\n{attachment}"

        super().__init__(self.message)


# class OlostepRateLimitError(OlostepAPIError):
#     """Raised when rate limit is exceeded or payment is required."""

#     def __init__(
#         self,
#         status_code: int,
#         message: str,
#         response_data: dict[str, Any] | None = None
#     ) -> None:
#         super().__init__(status_code, message, response_data)


#########################
# Client side errors
#########################
class OlostepClientError_BaseError(Olostep_BaseError):
    """Raised when an error occurs on the client side."""

    pass


class OlostepClientError_RequestValidationFailed(OlostepClientError_BaseError):
    """Raised when request validation fails."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        self.errors = errors
        self.message = "The request is invalid"

        for error in errors:
            self.message = f"{self.message}\nField: {error['type']} {error['loc']}, Error: {error['msg']}"
        super().__init__(self.message)


class OlostepClientError_ResponseValidationFailed(OlostepClientError_BaseError):
    """Raised when request validation fails."""

    def __init__(
        self,
        request: RawAPIRequest,
        response: RawAPIResponse,
        errors: list[dict[str, Any]],
    ) -> None:
        self.request = request
        self.response = response

        self.errors = errors
        self.message = f"The response from '{request.url}' was invalid"

        for error in errors:
            self.message = f"{self.message}\nField: {error['type']} {error['loc']}, Error: {error['msg']}"
        super().__init__(self.message)


class OlostepClientError_NoAPIKey(OlostepClientError_BaseError):
    """Raised when no API key is provided in init nor found in environment."""

    def __init__(self) -> None:
        super().__init__(
            "Olostep API key is required and was neither provided nor found in the environment."
        )


class OlostepClientError_AsyncContext(OlostepClientError_BaseError):
    """Raised when an async context is required but not provided."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class OlostepClientError_BetaFeatureAccessRequired(OlostepClientError_BaseError):
    """Raised when a beta feature is used and the client is not whitelisted."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class OlostepClientError_Timeout(OlostepClientError_BaseError):
    """Raised when a wait operation times out on the client side."""

    def __init__(self, operation: str, timeout_seconds: int) -> None:
        self.operation = operation
        self.timeout_seconds = timeout_seconds
        message = f"Operation '{operation}' timed out after {timeout_seconds} seconds"
        super().__init__(message)
