def main():
    from security_contract import deny_external_network
    from security_contract import isolated_environment

    with isolated_environment():
        deny_external_network()
        import pytest

        raise SystemExit(pytest.main(["-q", "tests/test_cross_page_setting.py"]))


if __name__ == "__main__":
    main()
