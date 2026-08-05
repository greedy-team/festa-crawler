import pytest

import discover


@pytest.fixture(autouse=True)
def _no_sitemap_network(monkeypatch):
    """테스트가 실제 사이트맵을 받지 않도록 기본값을 빈 목록으로 둔다.

    사이트맵을 쓰는 테스트는 이 값을 직접 덮어쓴다.
    """
    monkeypatch.setattr(discover, "_sitemap_urls", [])
