from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from wsgiref.util import setup_testing_defaults


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402


class Phase1ApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(ROOT)

    def test_search_oom_returns_sop_001(self) -> None:
        status, _, payload = self.request_json("GET", "/v1/search", "q=OOM")

        self.assertEqual(status, 200)
        self.assertEqual(payload["results"][0]["id"], "sop-001")
        self.assertEqual(payload["results"][1]["id"], "sop-007")

    def test_search_page_builds_clickable_document_links(self) -> None:
        status, headers, body = self.request("GET", "/v1", "q=OOM")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        html = body.decode("utf-8")
        self.assertIn('value="OOM"', html)
        self.assertIn('data-version="v1"', html)
        self.assertIn('href="/v1/documents/sop-001"', html)
        self.assertIn('href="/v1"', html)
        self.assertIn('href="/v2"', html)
        self.assertIn('<strong class="hit">OOM</strong>', html)
        self.assertIn('const ACTIVE_VERSION = "v1"', html)
        self.assertIn('oncall.pageState.', html)
        self.assertIn('form.requestSubmit', html)

    def test_search_fault_returns_multiple_documents(self) -> None:
        status, _, payload = self.request_json("GET", "/v1/search", "q=故障")

        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(payload["results"]), 2)

    def test_search_replication_ignores_script_content(self) -> None:
        status, _, payload = self.request_json("GET", "/v1/search", "q=replication")

        self.assertEqual(status, 200)
        self.assertEqual(payload["results"], [])

    def test_search_cdn_hits_frontend_and_network_documents(self) -> None:
        status, _, payload = self.request_json("GET", "/v1/search", "q=CDN")

        self.assertEqual(status, 200)
        result_ids = [item["id"] for item in payload["results"]]
        result_scores = [item["score"] for item in payload["results"]]
        self.assertEqual(result_ids[:2], ["sop-010", "sop-003"])
        self.assertEqual(result_scores, sorted(result_scores, reverse=True))

    def test_search_ampersand_hits_decoded_content(self) -> None:
        status, _, payload = self.request_json("GET", "/v1/search", "q=&")

        self.assertEqual(status, 200)
        self.assertEqual(payload["query"], "&")
        result_ids = {item["id"] for item in payload["results"]}
        self.assertIn("sop-010", result_ids)
        self.assertNotIn("sop-008", result_ids)

    def test_search_encoded_ampersand_hits_decoded_content(self) -> None:
        status, _, payload = self.request_json("GET", "/v1/search", "q=%26")

        self.assertEqual(status, 200)
        self.assertEqual(payload["query"], "&")
        result_ids = {item["id"] for item in payload["results"]}
        self.assertIn("sop-010", result_ids)
        self.assertNotIn("sop-008", result_ids)

    def test_document_upsert_replaces_existing_content(self) -> None:
        first_status, _, first_payload = self.request_json(
            "POST",
            "/v1/documents",
            body={
                "id": "custom-doc",
                "html": (
                    "<html><head><title>Custom Alpha</title></head>"
                    "<body><main><p>alpha &amp; beta visible</p></main>"
                    "<script>replication only in script</script></body></html>"
                ),
            },
        )
        self.assertEqual(first_status, 201)
        self.assertEqual(first_payload["title"], "Custom Alpha")

        search_alpha_status, _, search_alpha_payload = self.request_json(
            "GET", "/v1/search", "q=alpha"
        )
        self.assertEqual(search_alpha_status, 200)
        self.assertEqual(search_alpha_payload["results"][0]["id"], "custom-doc")

        second_status, _, second_payload = self.request_json(
            "POST",
            "/v1/documents",
            body={
                "id": "custom-doc",
                "html": (
                    "<html><head><title>Custom Gamma</title></head>"
                    "<body><main><p>gamma only</p></main></body></html>"
                ),
            },
        )
        self.assertEqual(second_status, 201)
        self.assertEqual(second_payload["title"], "Custom Gamma")

        search_old_status, _, search_old_payload = self.request_json(
            "GET", "/v1/search", "q=alpha"
        )
        self.assertEqual(search_old_status, 200)
        old_ids = {item["id"] for item in search_old_payload["results"]}
        self.assertNotIn("custom-doc", old_ids)

        search_new_status, _, search_new_payload = self.request_json(
            "GET", "/v1/search", "q=gamma"
        )
        self.assertEqual(search_new_status, 200)
        self.assertEqual(search_new_payload["results"][0]["id"], "custom-doc")

    def test_title_text_is_not_searchable(self) -> None:
        status, _, payload = self.request_json(
            "POST",
            "/v1/documents",
            body={
                "id": "title-only",
                "html": (
                    "<html><head><title>OnlyTitleToken</title></head>"
                    "<body><main><p>body without the token</p></main></body></html>"
                ),
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["title"], "OnlyTitleToken")

        search_status, _, search_payload = self.request_json(
            "GET", "/v1/search", "q=OnlyTitleToken"
        )
        self.assertEqual(search_status, 200)
        result_ids = {item["id"] for item in search_payload["results"]}
        self.assertNotIn("title-only", result_ids)

    def test_document_detail_route_returns_html_page(self) -> None:
        status, headers, body = self.request("GET", "/v1/documents/sop-001")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("Content-Security-Policy", headers)
        html = body.decode("utf-8")
        self.assertIn("<title>后端服务 On-Call SOP</title>", html)
        self.assertIn("场景二：单服务OOM崩溃", html)

    def request_json(
        self,
        method: str,
        path: str,
        query_string: str = "",
        body: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, str], dict[str, object]]:
        status, headers, raw_body = self.request(method, path, query_string, body)
        return status, headers, json.loads(raw_body.decode("utf-8"))

    def request(
        self,
        method: str,
        path: str,
        query_string: str = "",
        body: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        environ: dict[str, object] = {}
        setup_testing_defaults(environ)
        environ["REQUEST_METHOD"] = method
        environ["PATH_INFO"] = path
        environ["QUERY_STRING"] = query_string

        raw_body = b""
        if body is not None:
            raw_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            environ["CONTENT_LENGTH"] = str(len(raw_body))
            environ["CONTENT_TYPE"] = "application/json"
        else:
            environ["CONTENT_LENGTH"] = "0"
        environ["wsgi.input"] = BytesIO(raw_body)

        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        body_chunks = b"".join(self.app(environ, start_response))
        status_line = str(captured["status"])
        status_code = int(status_line.split(" ", 1)[0])
        headers = dict(captured["headers"])
        return status_code, headers, body_chunks


if __name__ == "__main__":
    unittest.main()
