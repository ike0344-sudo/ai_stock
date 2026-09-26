def pytest_configure(config):
    config.addinivalue_line("markers", "parity: 기존 코드와의 패리티(실데이터 필요, 없으면 skip)")
