from __future__ import annotations

from io import BytesIO
import json
import tempfile
from pathlib import Path
import sys
import unittest
from wsgiref.util import setup_testing_defaults

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from phase2.chunking import chunk_html_document  # noqa: E402
from phase2.rebuild_index import rebuild_semantic_index  # noqa: E402
from phase2.service import LocalSemanticSearchService  # noqa: E402


class FakeLocalEmbeddingProvider:
    model_name = "test-local-bge"
    backend_name = "test"
    embedding_dim = 8

    def __init__(self) -> None:
        self._concepts = (
            ("backend", ("后端", "后端服务", "服务器", "oom", "超时", "熔断", "降级", "pod", "jvm")),
            ("infra", ("sre", "服务器", "kubernetes", "k8s", "节点", "集群", "etcd", "ingress")),
            ("outage", ("挂了", "故障", "崩溃", "异常", "不可用", "超时", "失败")),
            ("security", ("黑客", "入侵", "攻击", "漏洞", "ddos", "sql注入", "安全")),
            ("ai", ("机器学习", "模型", "推荐", "推理", "gpu", "算法", "特征")),
            ("database", ("数据库", "主从", "连接池", "mysql", "dba")),
            ("network", ("cdn", "dns", "带宽", "流量", "负载均衡")),
            ("frontend", ("前端", "白屏", "浏览器", "兼容性", "页面")),
        )

    def embed_queries(self, queries: list[str]) -> np.ndarray:
        return self._embed_many(queries)

    def embed_passages(self, passages: list[str]) -> np.ndarray:
        return self._embed_many(passages)

    def _embed_many(self, texts: list[str]) -> np.ndarray:
        vectors = [self._embed_one(text) for text in texts]
        if not vectors:
            return np.zeros((0, self.embedding_dim), dtype=np.float32)
        return np.vstack(vectors).astype(np.float32)

    def _embed_one(self, text: str) -> np.ndarray:
        lowered = text.casefold()
        vector = np.full(self.embedding_dim, 0.01, dtype=np.float32)

        for index, (_name, aliases) in enumerate(self._concepts):
            weight = 0.0
            for alias in aliases:
                if alias.casefold() in lowered:
                    weight += 1.0
            vector[index] += weight

        if "后端服务 on-call sop" in lowered:
            vector[0] += 4.0
            vector[2] += 1.5
        if "sre基础设施 on-call sop" in lowered:
            vector[1] += 4.0
            vector[2] += 1.5
        if "信息安全 on-call sop" in lowered:
            vector[3] += 2.5
        if "ai算法 on-call sop" in lowered:
            vector[4] += 3.0
        if "服务器挂了" in lowered:
            vector[0] += 3.0
            vector[1] += 3.0
            vector[2] += 1.0

        norm = float(np.linalg.norm(vector))
        if norm <= 1e-12:
            return vector
        return vector / norm


class Phase2ApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.index_dir = Path(self.temp_dir.name) / "semantic-index"
        self.provider = FakeLocalEmbeddingProvider()
        rebuild_semantic_index(
            data_dir=ROOT / "data",
            index_dir=self.index_dir,
            provider=self.provider,
        )
        self.semantic_service = LocalSemanticSearchService(
            index_dir=self.index_dir,
            provider=self.provider,
        )
        self.app = create_app(ROOT, semantic_service=self.semantic_service)

    def test_chunker_handles_malformed_sre_html(self) -> None:
        html = (ROOT / "data" / "sop-004.html").read_text(encoding="utf-8")
        document = chunk_html_document("sop-004", html)

        self.assertGreater(len(document.chunks), 3)
        sections = [chunk.section_path for chunk in document.chunks]
        self.assertIn("三、常见故障处理 / 场景一：Kubernetes节点NotReady", sections)
        self.assertIn("三、常见故障处理 / 场景二：Etcd集群异常", sections)

    def test_search_server_down_ranks_backend_and_sre_near_top(self) -> None:
        status, _, payload = self.request_json("GET", "/v2/search", "q=服务器挂了")

        self.assertEqual(status, 200)
        top_ids = [item["id"] for item in payload["results"][:2]]
        self.assertEqual(set(top_ids), {"sop-001", "sop-004"})

    def test_search_hacker_attack_ranks_security_first(self) -> None:
        status, _, payload = self.request_json("GET", "/v2/search", "q=黑客攻击")

        self.assertEqual(status, 200)
        self.assertEqual(payload["results"][0]["id"], "sop-005")

    def test_search_machine_learning_issue_ranks_ai_first(self) -> None:
        status, _, payload = self.request_json(
            "GET", "/v2/search", "q=机器学习模型出问题"
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["results"][0]["id"], "sop-008")

    def test_search_results_are_sorted_by_score(self) -> None:
        status, _, payload = self.request_json("GET", "/v2/search", "q=黑客攻击")

        self.assertEqual(status, 200)
        scores = [item["score"] for item in payload["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_search_page_uses_v2_document_links(self) -> None:
        status, headers, body = self.request("GET", "/v2", "q=黑客攻击")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        html = body.decode("utf-8")
        self.assertIn('data-version="v2"', html)
        self.assertIn('href="/v1"', html)
        self.assertIn('href="/v2"', html)
        self.assertIn('action="/v2"', html)
        self.assertIn('href="/v2/documents/sop-005"', html)
        self.assertIn('const ACTIVE_VERSION = "v2"', html)
        self.assertIn('oncall.pageState.', html)
        self.assertIn('form.requestSubmit', html)

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
