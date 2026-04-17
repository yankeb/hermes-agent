import grok_bridge_mcp as gbm


def test_mcp_module_reports_availability_flag():
    assert isinstance(gbm._MCP_SERVER_AVAILABLE, bool)


def test_create_mcp_server_or_raise_importerror():
    if gbm._MCP_SERVER_AVAILABLE:
        server = gbm.create_mcp_server()
        assert server is not None
    else:
        try:
            gbm.create_mcp_server()
        except ImportError:
            return
        raise AssertionError("Expected ImportError when MCP package is unavailable")
