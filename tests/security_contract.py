import asyncio
import inspect
import ipaddress
import os
import socket
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


@contextmanager
def isolated_environment():
    original_environment = dict(os.environ)
    system_environment = {
        key: value
        for key, value in original_environment.items()
        if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC"}
    }
    with tempfile.TemporaryDirectory(prefix="pdf2zh-security-contract-") as directory:
        os.environ.clear()
        os.environ.update(system_environment)
        os.environ.update(
            {
                "HOME": directory,
                "USERPROFILE": directory,
                "APPDATA": directory,
                "LOCALAPPDATA": directory,
                "XDG_CONFIG_HOME": directory,
                "XDG_CACHE_HOME": directory,
                "HF_HOME": directory,
                "HF_HUB_OFFLINE": "1",
                "GRADIO_ANALYTICS_ENABLED": "False",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "TEMP": directory,
                "TMP": directory,
                "TMPDIR": directory,
            }
        )
        try:
            yield Path(directory)
        finally:
            for module_name in ("babeldoc.translator.cache", "pdf2zh_next.translator.cache"):
                module = sys.modules.get(module_name)
                if module is not None and not module.db.is_closed():
                    module.db.close()
            os.environ.clear()
            os.environ.update(original_environment)


def deny_external_network():
    def loopback(host):
        if str(host).casefold() == "localhost":
            return True
        try:
            return ipaddress.ip_address(str(host).split("%", 1)[0]).is_loopback
        except ValueError:
            return False

    resolve = socket.getaddrinfo
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    sendto = socket.socket.sendto

    def guarded_resolve(host, *args, **kwargs):
        if not loopback(host):
            raise OSError("external DNS disabled in synthetic contract")
        return resolve(host, *args, **kwargs)

    def guarded_connect(connection, address):
        if not isinstance(address, tuple) or not loopback(address[0]):
            raise OSError("external connection disabled in synthetic contract")
        return connect(connection, address)

    def guarded_connect_ex(connection, address):
        if not isinstance(address, tuple) or not loopback(address[0]):
            raise OSError("external connection disabled in synthetic contract")
        return connect_ex(connection, address)

    def guarded_sendto(connection, *args):
        address = args[-1] if args else None
        if not isinstance(address, tuple) or not loopback(address[0]):
            raise OSError("external connection disabled in synthetic contract")
        return sendto(connection, *args)

    socket.getaddrinfo = guarded_resolve
    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.socket.sendto = guarded_sendto
    try:
        socket.getaddrinfo("example.invalid", 443)
    except OSError:
        pass
    else:
        raise AssertionError("external DNS guard did not reject")


def main():
    with isolated_environment() as directory:
        run_contract(directory)


def run_contract(directory):
    deny_external_network()
    sys.argv = ["security-contract"]
    from importlib.metadata import version

    import gradio
    import pdf2zh_next
    from pdf2zh_next import gui
    from pdf2zh_next import high_level
    from pdf2zh_next.config.model import SettingsModel
    from pdf2zh_next.config.translate_engine_model import (
        TERM_EXTRACTION_ENGINE_METADATA,
    )
    from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA
    from pdf2zh_next.config.translate_engine_model import GoogleSettings
    from pdf2zh_next.high_level import do_translate_async_stream

    assert version("gradio") == "6.32.0"
    assert version("gradio-client") == "2.7.2"
    assert version("gradio-pdf") == "0.0.24"
    assert version("pillow") == "13.0.0"
    assert pdf2zh_next.__version__ == "2.10.2+pwo.1.crosspage.2"
    assert TRANSLATION_ENGINE_METADATA and TERM_EXTRACTION_ENGINE_METADATA
    assert inspect.isasyncgenfunction(do_translate_async_stream)
    settings = SettingsModel(translate_engine_settings=GoogleSettings())
    assert settings.translation is not None
    from babeldoc import _rust_il
    from babeldoc.format.pdf import translation_config
    from pdf2zh_next.high_level import supports_experimental_cross_page_context

    assert settings.translation.experimental_cross_page_context is False
    assert supports_experimental_cross_page_context() is True
    assert type(translation_config.CROSS_PAGE_SENTENCE_PROTOCOL_VERSION) is int
    assert translation_config.CROSS_PAGE_SENTENCE_PROTOCOL_VERSION == 1
    assert type(_rust_il.CROSS_PAGE_SENTENCE_PROTOCOL_VERSION) is int
    assert _rust_il.CROSS_PAGE_SENTENCE_PROTOCOL_VERSION == 1
    assert _rust_il.stage_capture_enabled() is False
    assert isinstance(gui.demo, gradio.Blocks)

    async def check_stream():
        source = directory / "synthetic.pdf"
        source.write_bytes(b"%PDF-1.4")
        settings.basic.debug = False
        calls = []

        async def synthetic_stream(received_settings, received_file):
            calls.append((received_settings, received_file))
            yield {"type": "progress_start"}
            yield {"type": "finish"}

        with patch.object(type(settings), "validate_settings"), patch.object(
            high_level, "_translate_in_subprocess", synthetic_stream
        ):
            events = [event async for event in do_translate_async_stream(settings, source)]
        assert [event["type"] for event in events] == ["progress_start", "finish"]
        assert calls == [(settings, source)]

        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def cancellable_stream(_settings, _file):
            try:
                started.set()
                await asyncio.Event().wait()
                yield {"type": "finish"}
            finally:
                cleaned.set()

        async def consume():
            return [event async for event in do_translate_async_stream(settings, source)]

        with patch.object(type(settings), "validate_settings"), patch.object(
            high_level, "_translate_in_subprocess", cancellable_stream
        ):
            task = asyncio.create_task(consume())
            await asyncio.wait_for(started.wait(), timeout=5)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("cancelled stream returned normally")
        assert cleaned.is_set()

    asyncio.run(check_stream())
    original_launch = gui.demo.launch
    original_auth = gui.parse_user_passwd
    try:
        for authenticated in (False, True):
            for failures in range(3):
                calls = []

                def launch(call_log=calls, failed_attempts=failures, **kwargs):
                    call_log.append(kwargs)
                    if len(call_log) <= failed_attempts:
                        raise OSError("synthetic bind failure")

                gui.demo.launch = launch
                gui.parse_user_passwd = lambda *_, enabled=authenticated: ([('synthetic', 'synthetic')] if enabled else None, 'synthetic')
                gui.setup_gui(auth_file="synthetic" if authenticated else None, server_port=7860, inbrowser=False)
                assert len(calls) == failures + 1
                for call in calls:
                    assert call["theme"] is gui.gui_theme and call["css"] == gui.custom_css
                    assert call["inbrowser"] is False
                    assert call["allowed_paths"] == [str(path) for path in gui.pdf_preview_allowed_paths]
                    assert ("auth" in call) is authenticated
                assert calls[0]["server_name"] == ".".join(["0"] * 4)
                if failures >= 1:
                    assert calls[1]["server_name"] == "127.0.0.1"
                if failures == 2:
                    assert "server_name" not in calls[2] and calls[2]["share"] is True
    finally:
        gui.demo.launch = original_launch
        gui.parse_user_passwd = original_auth
    print("Synthetic settings, metadata, stream, cancellation and six mocked launch paths passed")


if __name__ == "__main__":
    main()
