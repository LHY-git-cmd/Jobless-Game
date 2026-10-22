"""静态缓存契约：页面与模块可验证更新，素材可缓存，API 仍禁止存储。"""

from pathlib import Path
import re
from unittest import TestCase

from fastapi.testclient import TestClient
from backend.app.main import app

ROOT = Path(__file__).resolve().parents[2]


class StaticCacheTests(TestCase):
    """通过本地真实静态处理器核验缓存头和条件请求，不连接数据库。"""

    def test_entrypoints_modules_and_styles_revalidate(self):
        """HTML、JS、CSS 包括 304 都要求重新验证，ETag 继续工作。"""
        with TestClient(app) as client:
            for path in ("/", "/forum.html", "/src/main.js", "/styles.css", "/src/pages/home.js",
                         "/src/games/mine/controller.js", "/styles/base.css", "/styles/pages/mine.css"):
                with self.subTest(path=path):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers.get("cache-control"), "no-cache")
                    cached = client.get(path, headers={"If-None-Match": response.headers["etag"]})
                    self.assertEqual(cached.status_code, 304)
                    self.assertEqual(cached.headers.get("cache-control"), "no-cache")

    def test_assets_and_api_keep_separate_policies(self):
        """音频允许七天缓存，未知 API 路径也不被静态缓存策略覆盖。"""
        with TestClient(app) as client:
            asset = client.get("/assets/audio/explosion.wav")
            self.assertIn("max-age=604800", asset.headers.get("cache-control", ""))
            api = client.get("/api/nonexistent-cache-probe")
            self.assertEqual(api.headers.get("cache-control"), "no-store")

    def test_both_nginx_templates_revalidate_and_preserve_asset_cache(self):
        """两套部署模板具备同一静态策略，错误响应也携带验证指令。"""
        for relative in ("backend/deploy/docker/nginx.conf", "backend/deploy/nginx-site.conf.example"):
            with self.subTest(template=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                location = re.search(r"location / \{([^}]+)\}", source).group(1)
                self.assertIn("add_header Cache-Control no-cache always;", location)
                self.assertRegex(source, r"location /assets/ \{\s*expires 7d;")

    def test_production_scripts_and_styles_have_no_manual_versions(self):
        """仅约束生产 HTML/JS 引用，不限制测试的 ?reload 参数或素材版本。"""
        frontend = ROOT / "frontend"
        for path in (*frontend.glob("*.html"), *frontend.joinpath("src").rglob("*.js")):
            with self.subTest(file=path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"\.(?:js|css)\?v=")
