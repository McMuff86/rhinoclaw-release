"""
Tests for rhinoclaw.utils.errors module.
"""
import pytest
from rhinoclaw.utils.errors import ErrorCode, get_connection_error_code


class TestErrorCode:
    """Tests for ErrorCode constants."""

    def test_connection_error_codes_exist(self):
        assert ErrorCode.CONNECTION_ERROR == "CONNECTION_ERROR"
        assert ErrorCode.CONNECTION_TIMEOUT == "CONNECTION_TIMEOUT"
        assert ErrorCode.CONNECTION_REFUSED == "CONNECTION_REFUSED"

    def test_validation_error_codes_exist(self):
        assert ErrorCode.INVALID_PARAMS == "INVALID_PARAMS"
        assert ErrorCode.MISSING_PARAMS == "MISSING_PARAMS"
        assert ErrorCode.INVALID_TYPE == "INVALID_TYPE"
        assert ErrorCode.INVALID_ID == "INVALID_ID"

    def test_rhino_error_codes_exist(self):
        assert ErrorCode.RHINO_ERROR == "RHINO_ERROR"
        assert ErrorCode.RHINO_COMMAND_FAILED == "RHINO_COMMAND_FAILED"
        assert ErrorCode.RHINO_OBJECT_NOT_FOUND == "RHINO_OBJECT_NOT_FOUND"

    def test_object_error_codes_exist(self):
        assert ErrorCode.CREATE_OBJECT_ERROR == "CREATE_OBJECT_ERROR"
        assert ErrorCode.MODIFY_OBJECT_ERROR == "MODIFY_OBJECT_ERROR"
        assert ErrorCode.DELETE_OBJECT_ERROR == "DELETE_OBJECT_ERROR"


class TestGetConnectionErrorCode:
    """Tests for get_connection_error_code() function."""

    def test_timeout_detection(self):
        exc = Exception("Socket timeout while waiting")
        assert get_connection_error_code(exc) == ErrorCode.CONNECTION_TIMEOUT

    def test_refused_detection(self):
        exc = Exception("Connection refused")
        assert get_connection_error_code(exc) == ErrorCode.CONNECTION_REFUSED

    def test_connect_keyword_detection(self):
        exc = Exception("Could not connect to host")
        assert get_connection_error_code(exc) == ErrorCode.CONNECTION_REFUSED

    def test_connection_keyword_detection(self):
        exc = Exception("lost the network link")
        result = get_connection_error_code(exc)
        assert result == ErrorCode.UNKNOWN_ERROR

    def test_unknown_error(self):
        exc = Exception("Some random error")
        assert get_connection_error_code(exc) == ErrorCode.UNKNOWN_ERROR

    def test_case_insensitive(self):
        exc = Exception("TIMEOUT occurred")
        assert get_connection_error_code(exc) == ErrorCode.CONNECTION_TIMEOUT
