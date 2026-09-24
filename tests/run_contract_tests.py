#!/usr/bin/env python3
"""契约测试（stdlib 跑法，不依赖 pytest）。

覆盖：契约校验错误码 / 超预算 / golden 用例 / 同 state 连打 N 次的稳定性 / HTTP 端点。
用法：python tests/run_contract_tests.py（任意装了本项目依赖的解释器，建议项目 venv）
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from laya_api.client import InProcessEngine, ThresholdRouter  # noqa: E402
from laya_api.models import ApiError, DecideRequest  # noqa: E402

GOLDEN = json.loads((ROOT / "tests" / "golden" / "cases.json").read_text(encoding="utf-8"))
ENGINE_MODE = os.getenv("LAYA_ENGINE", "laya_mlx").strip().lower()
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
        PASSED.append(name)
        print(f"  PASS  {name}")
    except Exception as exc:  # noqa: BLE001
        FAILED.append(name)
        print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
        traceback.print_exc(limit=3)


def expect_error(code: str, fn) -> None:
    try:
        fn()
    except ApiError as exc:
        assert exc.code == code, f"期望 {code}，实际 {exc.code}（{exc.message}）"
        return
    raise AssertionError(f"期望抛出 {code}，但没有抛")


def main() -> int:
    eng = InProcessEngine(engine_mode=ENGINE_MODE)
    print(f"== 引擎模式：{ENGINE_MODE} ==")
    print("== 预热（加载模型，缓存后热调用毫秒级）==")
    print("  ", eng.warm())

    if ENGINE_MODE == "laya_mlx":
        def independence() -> None:
            import sys as _sys
            leaked = [m for m in _sys.modules if m.split(".")[0] in
                      {"hermes", "hermes_laya", "hermes_cli", "agent", "gateway"}]
            assert not leaked, f"独立模式下仍导入了 Hermes 模块：{leaked[:5]}"

        check("独立模式未导入任何 Hermes 模块", independence)

    # ---------------- 契约校验
    print("== 契约校验 ==")

    check("questions 与 preset 二选一", lambda: expect_error(
        "SCHEMA_INVALID", lambda: eng.decide("x")))

    check("choice 标签重复 → SCHEMA_INVALID", lambda: expect_error(
        "SCHEMA_INVALID",
        lambda: eng.decide("x", questions={"a": {"type": "choice", "instructions": "i", "criteria": ["x", "x"]}})))

    check("score 需要非空 criteria", lambda: expect_error(
        "SCHEMA_INVALID",
        lambda: eng.decide("x", questions={"a": {"type": "score", "instructions": "i", "criteria": []}})))

    check("noul criteria 必须是 dict", lambda: expect_error(
        "SCHEMA_INVALID",
        lambda: eng.decide("x", questions={"a": {"type": "noul", "instructions": "i", "criteria": ["bad"]}})))

    check("选项数超 max_options → OVER_BUDGET", lambda: expect_error(
        "OVER_BUDGET",
        lambda: eng.decide({"body": "x"}, policy={"max_options": 3},
                           questions={"a": {"type": "choice", "instructions": "i",
                                            "criteria": ["a", "b", "c", "d"]}})))

    check("state 超限且 truncate_state=false → OVER_BUDGET", lambda: expect_error(
        "OVER_BUDGET",
        lambda: eng.decide("x" * 5000, policy={"max_state_chars": 100, "truncate_state": False},
                           questions={"a": {"type": "noul", "instructions": "i"}})))

    check("state_format=json 但 state 不是对象 → SCHEMA_INVALID", lambda: expect_error(
        "SCHEMA_INVALID",
        lambda: eng.decide("plain", state_format="json",
                           questions={"a": {"type": "noul", "instructions": "i"}})))

    check("state 截断 → warning", lambda: (
        lambda r: (_ for _ in ()).throw(AssertionError(f"未出现 state_truncated: {r.warnings}"))
        if "state_truncated" not in r.warnings else None)(
        eng.decide("这" * 5000, policy={"max_state_chars": 200},
                   questions={"a": {"type": "noul", "instructions": "需要人工吗"}})))

    # ---------------- golden 用例
    print("== golden 用例 ==")
    drift = float(GOLDEN.get("max_probability_drift", 0.01))
    runs = int(GOLDEN.get("stability_runs", 10))

    for case in GOLDEN["cases"]:
        name = case["name"]

        def run_case(case=case) -> None:
            kwargs = {"questions": case["questions"]} if "questions" in case else {"preset": case["preset"]}
            r = eng.decide(case["state"], **kwargs)
            assert r.answers, f"{name}: 无 answers"
            for qid, expect in (case.get("expect_choice") or {}).items():
                got = r.answers[qid].get("choice")
                assert got == expect, f"{name}: {qid} 期望 {expect}，实际 {got}"
            for qid, min_conf in (case.get("expect_min_confidence") or {}).items():
                conf = float(r.answers[qid]["confidence"])
                assert conf >= float(min_conf), f"{name}: {qid} 置信度 {conf} < {min_conf}"
            for qid, qtype in (case.get("expect_answer_types") or {}).items():
                assert r.answers[qid]["type"] == qtype, f"{name}: {qid} 类型不符"
            for qid, total in (case.get("expect_probabilities_sum") or {}).items():
                s = sum(float(v) for v in r.answers[qid]["probabilities"].values())
                assert abs(s - float(total)) < 0.02, f"{name}: {qid} 概率和 {s} 偏离 {total}"
            if case.get("expect_nonempty_answers"):
                assert len(r.answers) >= 1

        check(f"golden:{name}", run_case)

        def run_stability(case=case) -> None:
            if "questions" not in case or not case.get("expect_choice"):
                return
            qid = next(iter(case["expect_choice"]))
            first = eng.decide(case["state"], questions=case["questions"], policy={"return_probabilities": True})
            base = dict(first.answers[qid].get("probabilities") or {})
            for _ in range(max(0, runs - 1)):
                again = eng.decide(case["state"], questions=case["questions"], policy={"return_probabilities": True})
                assert again.answers[qid]["choice"] == first.answers[qid]["choice"], "标签不稳定"
                for label, p in (again.answers[qid].get("probabilities") or {}).items():
                    assert abs(float(p) - float(base[label])) <= drift, f"概率漂移 {label}: {p} vs {base[label]}"

        check(f"stability:{name}(x{runs})", run_stability)

    # ---------------- 语义层（choose/rate/yes_no）
    print("== 语义层封装 ==")

    def sem_choose() -> None:
        a = eng.choose({"body": "账单重复扣款，请退款"}, "该分给哪个团队？",
                       {"billing": "退款/计费", "technical": "故障/缺陷"}, tau=0.6)
        assert a.kind == "choice" and a.label == "billing", a
        assert a.auto is True and a.needs_review is False
        assert abs(sum(v for v in a.distribution.values() if v) - 1.0) < 0.02, a.distribution
        assert a.distribution["billing"] > 0.9

    check("choose 选择类：标签+分布+阈值判定", sem_choose)

    def sem_rate() -> None:
        a = eng.rate({"body": "系统登录失败，全组都无法使用"}, "紧急程度", ["low", "medium", "high"], tau=0.6)
        assert a.kind == "score" and 0 <= a.score <= 2, a
        assert a.level in ("low", "medium", "high"), a.level
        assert set(a.distribution) == {"low", "medium", "high"}, a.distribution
        assert a.needs_review is True, "该样例置信度低，应提示复核"

    check("rate 程度类：分数+档位+分布", sem_rate)

    def sem_yes_no() -> None:
        a = eng.yes_no({"body": "账单重复扣款，请退款"}, "需要人工介入吗", tau=0.6)
        assert a.kind == "yes_no" and isinstance(a.answer, bool), a
        assert 0.0 <= a.probability <= 1.0 and a.label in ("yes", "no")
        assert a.answer is False, a

    check("yes_no 是非类：布尔+概率", sem_yes_no)

    # ---------------- 阈值路由
    print("== 阈值路由 ==")

    def route_low_conf() -> None:
        r = eng.decide({"body": "系统登录失败，全组都无法使用"},
                       questions={"urgency": {"type": "score", "instructions": "紧急程度",
                                              "criteria": ["low", "medium", "high"]}})
        router = ThresholdRouter(thresholds={"urgency": 0.99}, default=0.99,
                                 fallback=lambda state, qs: {"route": "llm", "questions": list(qs)})
        out = router.route({"body": "..."}, {"urgency": {}}, r)
        assert out["needs_review"], "高阈值下应有待复核项"
        assert out["fallback_result"]["route"] == "llm", "回退未被调用"

    check("低置信度触发回退", route_low_conf)

    # ---------------- 鉴权与限流（环境变量驱动）
    print("== 鉴权 / 限流 / 配置回显 ==")

    def auth_flow() -> None:
        import httpx
        from laya_api import auth as A, settings as S
        from laya_api.server import app as srv

        body = {"state": {"body": "账单重复扣款，请退款"},
                "questions": {"department": {"type": "choice", "instructions": "该由哪个团队处理？",
                                             "criteria": {"billing": "退款/计费", "technical": "故障/缺陷"}}}}

        def apply_env(**env: str) -> None:
            for k, v in env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            S.reload_from_env()
            A.guard.refresh()

        async def go() -> None:
            transport = httpx.ASGITransport(app=srv)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                # 1) 关闭鉴权：直接可调
                assert (await c.post("/v1/decide", json=body)).status_code == 200

                # 2) 打开鉴权（两把密钥 + 每分钟 3 次限流）
                apply_env(LAYA_AUTH_MODE="api_key", LAYA_API_KEYS="k1,k2",
                          LAYA_RATE_LIMIT_PER_MIN="3", LAYA_RATE_LIMIT_BURST="3")

                assert (await c.get("/healthz")).status_code == 200, "健康检查应公开"
                r = await c.post("/v1/decide", json=body)
                assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED", r.text
                assert (await c.post("/v1/decide", json=body, headers={"X-API-Key": "wrong"})).status_code == 401
                ok = await c.post("/v1/decide", json=body, headers={"Authorization": "Bearer k1"})
                assert ok.status_code == 200, ok.text

                codes = []
                for _ in range(6):
                    rr = await c.post("/v1/decide", json=body, headers={"X-API-Key": "k2"})
                    codes.append(rr.status_code)
                assert 429 in codes, f"限流未生效：{codes}"
                limited = await c.post("/v1/decide", json=body, headers={"X-API-Key": "k2"})
                assert limited.status_code == 429 and limited.headers.get("Retry-After"), limited.headers
                assert limited.json()["error"]["code"] == "RATE_LIMITED"

                st = await c.get("/v1/status", headers={"X-API-Key": "k1"})
                cfg = st.json()["config"]
                assert cfg["auth"]["mode"] == "api_key" and cfg["auth"]["keys_configured"] == 2, cfg
                assert "k1" not in st.text and "k2" not in st.text, "状态接口泄露了密钥"

        try:
            asyncio.run(go())
        finally:
            apply_env(LAYA_AUTH_MODE="off", LAYA_API_KEYS=None,
                      LAYA_RATE_LIMIT_PER_MIN=None, LAYA_RATE_LIMIT_BURST=None)

    check("鉴权：401/公开路径/双密钥/429+Retry-After/状态不泄密", auth_flow)

    # ---------------- HTTP 层
    print("== HTTP 层（ASGITransport）==")

    def http_flow() -> None:
        import httpx
        from laya_api.server import app

        async def go() -> None:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                ui = await c.get("/")
                assert ui.status_code == 200 and "Laya 决策服务" in ui.text, "测试台页面不可用"
                wiki = await c.get("/wiki")
                assert wiki.status_code == 200, wiki.text
                for marker in ("接口", "数据模型", "错误码", "/v1/decide", "开发者文档"):
                    assert marker in wiki.text, f"文档页缺 {marker}"
                assert wiki.text.count("<table>") >= 4, "文档页表格没生成（应从 openapi 渲染）"
                # 边界守门：/wiki 只做接口参考，README/语义全文不许混进来（曾经混过）
                assert "语义说明全文" not in wiki.text, "/wiki 又混进 README 内容了"
                assert "一句话心智模型" not in wiki.text, "/wiki 混入了 docs/api-semantics.md 正文"
                assert len(wiki.text) < 40000, f"/wiki 体积失控：{len(wiki.text)} 字节（应只渲染 OpenAPI）"

                # 离线 Swagger UI / ReDoc：必须引用本地静态资源，不能有 CDN
                for path in ("/docs", "/redoc"):
                    page = await c.get(path)
                    assert page.status_code == 200, f"{path} 不可用"
                    assert "/static/swagger/" in page.text, f"{path} 未使用本地静态资源"
                    for cdn in ("cdn.jsdelivr.net", "unpkg.com", "fastapi.tiangolo.com"):
                        assert cdn not in page.text, f"{path} 仍然引用 CDN：{cdn}"
                for asset in ("swagger-ui-bundle.js", "swagger-ui.css", "redoc.standalone.js"):
                    a = await c.get(f"/static/swagger/{asset}")
                    assert a.status_code == 200 and len(a.content) > 1000, f"静态资源缺失：{asset}"

                # OpenAPI 范式自检：模型描述/示例/错误响应都要在 openapi.json 里
                oa = await c.get("/openapi.json")
                assert oa.status_code == 200, oa.text
                doc = oa.json()
                assert str(doc.get("openapi", "")).startswith("3."), doc.get("openapi")
                op = doc["paths"]["/v1/decide"]["post"]
                assert set(op["responses"]) >= {"200", "400", "413", "503", "504"}, op["responses"].keys()
                schemas = doc["components"]["schemas"]
                for name in ("DecideRequest", "DecideResponse", "ErrorResponse", "Policy", "Question"):
                    assert name in schemas, f"openapi 缺模型 {name}"
                props = schemas["DecideRequest"]["properties"]
                for field in ("state", "questions", "policy"):
                    assert props[field].get("description"), f"{field} 缺 description（文档会空）"
                assert schemas["Question"]["properties"]["type"].get("enum") == ["choice", "score", "noul"]

                # ── OpenAPI 3.0.3 降级文档：给只认 3.0.x 的平台导入（3.1 的 type:null / examples 数组都要降级）──
                oa30 = await c.get("/openapi-3.0.json")
                assert oa30.status_code == 200, oa30.text
                d30 = oa30.json()
                assert d30["openapi"] == "3.0.3", d30["openapi"]
                assert sorted(d30["paths"]) == sorted(doc["paths"]), "3.0 文档丢了端点"
                assert sorted(d30["components"]["schemas"]) == sorted(doc["components"]["schemas"]), "3.0 文档丢了模型"
                t30 = json.dumps(d30, ensure_ascii=False)
                assert '"type": "null"' not in t30, "3.1 的 type:null 未降级为 nullable"
                assert '"examples": [' not in t30, "3.1 的 schema 级 examples 未降级为 example"
                assert '"const"' not in t30, "const 未降级为 enum"
                assert d30.get("servers"), "3.0 文档缺 servers（部分平台必需）"
                for _p, _ms in d30["paths"].items():
                    for _m, _op in _ms.items():
                        if _m in ("get", "post", "put", "delete", "patch"):
                            assert _op.get("operationId"), f"{_m.upper()} {_p} 缺 operationId（部分平台导入时必需）"
                try:  # 装了真校验器就按 3.0 规范校验（可选依赖）
                    from openapi_spec_validator import OpenAPIV30SpecValidator
                    OpenAPIV30SpecValidator(d30).validate()
                except ImportError:
                    pass

                # ── 苍穹档（再扁平一层）：无 $ref / 无 allOf·anyOf·oneOf / 每个 schema 节点都有 type ──
                kdresp = await c.get("/openapi-kingdee.json")
                assert kdresp.status_code == 200, kdresp.text
                kd = kdresp.json()
                assert kd["openapi"] == "3.0.3", kd["openapi"]
                tk = json.dumps(kd, ensure_ascii=False)
                for bad_kw in ('"$ref"', '"allOf"', '"anyOf"', '"oneOf"'):
                    assert bad_kw not in tk, f"扁平化档仍残留 {bad_kw}（自研转换器会 NPE）"
                _miss: list = []

                def _scan(_n, _p=""):
                    if isinstance(_n, dict):
                        if any(x in _n for x in ("type", "properties", "items", "enum", "additionalProperties")) and "type" not in _n:
                            _miss.append(_p)
                        for _k, _v in _n.items():
                            _scan(_v, f"{_p}.{_k}")
                    elif isinstance(_n, list):
                        for _i, _v in enumerate(_n):
                            _scan(_v, f"{_p}[{_i}]")

                _scan(kd)
                assert not _miss, f"扁平化档有节点缺 type：{_miss[:3]}"
                # example 必须是数据，不能是被压成 schema 的形状
                _bad_ex = json.dumps(kd, ensure_ascii=False).count('"example": {\n            "type": "object"')
                assert _bad_ex == 0, "example 被误处理成 schema"
                assert '"required": [' not in tk, "扁平化档仍带 required 数组（苍穹会报 can not cast to boolean）"
                try:
                    from openapi_spec_validator import OpenAPIV30SpecValidator
                    OpenAPIV30SpecValidator(kd).validate()
                except ImportError:
                    pass

                # LAYA_OPENAPI_VERSION=3.0 时，/openapi.json（含 /docs、/redoc）整体切成 3.0.3
                import os as _os
                from laya_api import settings as _S
                _os.environ["LAYA_OPENAPI_VERSION"] = "3.0"
                _S.reload_from_env()
                try:
                    sw = await c.get("/openapi.json")
                    assert sw.json()["openapi"] == "3.0.3", sw.json()["openapi"]
                finally:
                    _os.environ.pop("LAYA_OPENAPI_VERSION", None)
                    _S.reload_from_env()
                assert "加载状态" in ui.text or "ready=" in ui.text
                h = await c.get("/healthz")
                assert h.status_code == 200, h.text
                r = await c.get("/readyz", params={"warm": 1})
                assert r.status_code == 200 and r.json()["ready"], r.text
                s = await c.get("/v1/status")
                assert s.status_code == 200 and "queue" in s.json()
                p = await c.get("/v1/presets")
                assert p.status_code == 200 and isinstance(p.json()["presets"], list)
                body = json.loads((ROOT / "contract" / "examples" / "decide.request.json").read_text(encoding="utf-8"))
                d = await c.post("/v1/decide", json=body)
                assert d.status_code == 200, d.text
                payload = d.json()
                assert payload["api_version"] == "1" and payload["answers"], payload
                assert payload["usage"]["latency_ms"] >= 0
                # 错误契约
                bad = await c.post("/v1/decide", json={"state": "x",
                                                       "questions": {"a": {"type": "choice", "instructions": "i",
                                                                           "criteria": ["x", "x"]}}})
                assert bad.status_code == 400, bad.text
                assert bad.json()["error"]["code"] == "SCHEMA_INVALID", bad.text

        asyncio.run(go())

    check("HTTP /healthz /readyz /v1/status /v1/presets /v1/decide + 错误契约", http_flow)

    print(f"\n== 汇总：{len(PASSED)} passed, {len(FAILED)} failed ==")
    if FAILED:
        print("失败项：" + ", ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
