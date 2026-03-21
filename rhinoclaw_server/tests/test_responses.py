"""
Tests for rhinoclaw.utils.responses module.
"""
import pytest
from rhinoclaw.utils.responses import ok, error, from_exception
from rhinoclaw.utils.errors import ErrorCode


class TestOkResponse:
    """Tests for the ok() function."""

    def test_ok_with_message_only(self):
        result = ok(message="Success")
        assert result["success"] is True
        assert result["message"] == "Success"
        assert result["data"] is None

    def test_ok_with_data(self):
        result = ok(message="Created", data={"id": "123"})
        assert result["success"] is True
        assert result["message"] == "Created"
        assert result["data"] == {"id": "123"}

    def test_ok_empty(self):
        result = ok()
        assert result["success"] is True
        assert result["message"] == ""
        assert result["data"] is None


class TestErrorResponse:
    """Tests for the error() function."""

    def test_error_with_code(self):
        result = error(message="Failed", code=ErrorCode.CONNECTION_ERROR)
        assert result["success"] is False
        assert result["message"] == "Failed"
        assert result["code"] == "CONNECTION_ERROR"

    def test_error_with_data(self):
        result = error(message="Failed", code=ErrorCode.INVALID_PARAMS, data={"field": "name"})
        assert result["success"] is False
        assert result["data"] == {"field": "name"}

    def test_error_default_code(self):
        result = error(message="Unknown failure")
        assert result["code"] == ErrorCode.UNKNOWN_ERROR


class TestFromException:
    """Tests for the from_exception() function."""

    def test_from_exception_with_explicit_code(self):
        exc = Exception("Something went wrong")
        result = from_exception(exc, code=ErrorCode.RHINO_ERROR)
        assert result["success"] is False
        assert result["message"] == "Something went wrong"
        assert result["code"] == "RHINO_ERROR"

    def test_from_exception_auto_detect_timeout(self):
        exc = Exception("Connection timeout occurred")
        result = from_exception(exc)
        assert result["code"] == ErrorCode.CONNECTION_TIMEOUT

    def test_from_exception_auto_detect_refused(self):
        exc = Exception("Connection refused by host")
        result = from_exception(exc)
        assert result["code"] == ErrorCode.CONNECTION_REFUSED

    def test_from_exception_auto_detect_connection(self):
        exc = Exception("Connection lost")
        result = from_exception(exc)
        assert result["code"] == ErrorCode.CONNECTION_REFUSED

    def test_from_exception_no_auto_detect(self):
        exc = Exception("Random error")
        result = from_exception(exc, auto_detect=False)
        assert result["code"] == ErrorCode.UNKNOWN_ERROR
