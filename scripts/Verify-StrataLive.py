"""Explicit live checks using synthetic Japanese, images and dummy tools only.

API contracts: Niko1221/Strata v0.1.39 serve/server.py and docs/DETAILS.md.
This does not start/stop/load/unload a model or read a user project. Cancellation
closes only this verifier's own socket, after checking that the server was idle.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import http.client
import json
import os
from pathlib import Path
import socket
import struct
import sys
import time
from urllib.parse import urlsplit
import zlib


SUPPORTER = Path(__file__).resolve().parents[1]
CANONICAL = "qwen3.8-flash-next-iq3_s"
LEGACY_ALIAS = "qwen3.8-27b-local"


class VerificationError(RuntimeError):
    pass


class Client:
    def __init__(self, base_url: str, timeout: float):
        address = urlsplit(base_url)
        if address.scheme != "http" or address.hostname != "127.0.0.1" or address.path not in ("", "/"):
            raise VerificationError("Verification requires an HTTP loopback-only Strata base URL")
        self.host, self.port, self.timeout = address.hostname, address.port or 80, timeout
        self.api_key = os.environ.get("STRATA_API_KEY", "")

    def open(self, route: str, payload=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        connection.connect()
        owned_socket = connection.sock
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Connection": "close"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        try:
            connection.request("GET" if payload is None else "POST", route, body=body, headers=headers)
            response = connection.getresponse()
            if response.status >= 400:
                detail = response.read(8192).decode("utf-8", errors="replace")
                raise VerificationError(f"HTTP {response.status} {route}: {detail}")
            return connection, owned_socket, response
        except Exception:
            connection.close()
            if owned_socket is not None:
                owned_socket.close()
            raise

    def json(self, route: str, payload=None):
        connection, owned_socket, response = self.open(route, payload)
        try:
            return json.loads(response.read().decode("utf-8"))
        finally:
            response.close()
            connection.close()
            owned_socket.close()

    def idle_state(self):
        slots = self.json("/slots")
        status = self.json("/status")
        capabilities = self.json("/v1/status")
        if not isinstance(slots, list) or not slots:
            raise VerificationError("Cannot establish an idle loaded inference slot")
        if any(slot.get("is_processing") is not False for slot in slots):
            raise VerificationError("An inference slot is busy or its state is unknown")
        if status.get("busy") is not False or status.get("queued") != 0:
            raise VerificationError("Existing work is active/queued or its state is unknown")
        if capabilities.get("activity", {}).get("in_flight") != 0:
            raise VerificationError("Existing in-flight work is active or unknown")
        # /status can include the end of an earlier answer. Keep only the activity
        # fields needed for ownership checks in our synthetic verification logs.
        safe_slots = [{key: slot.get(key) for key in ("id", "n_ctx", "is_processing")} for slot in slots]
        return {"slots": safe_slots, "status": {"busy": False, "queued": 0}, "in_flight": 0}

    def wait_idle(self, timeout=90):
        deadline = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < deadline:
            try:
                return self.idle_state()
            except VerificationError as error:
                last_error = str(error)
            time.sleep(0.5)
        raise VerificationError("Slot did not become idle after this verifier's request: " + str(last_error))


def png_fixture(path: Path, swapped: bool):
    """White image with a red circle and blue square; swap their positions."""
    width, height = 448, 224
    circle_x, square_x = (336, 112) if swapped else (112, 336)
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            color = (255, 255, 255)
            if (x - circle_x) ** 2 + (y - 112) ** 2 <= 52 ** 2:
                color = (235, 25, 35)
            if abs(x - square_x) <= 52 and abs(y - 112) <= 52:
                color = (25, 60, 235)
            row.extend(color)
        rows.append(row)

    def chunk(kind, content):
        return struct.pack("!I", len(content)) + kind + content + struct.pack("!I", zlib.crc32(kind + content) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 2, 0, 0, 0)) +
                     chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def object_format(name: str, properties: dict):
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True,
            "schema": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}}}


def completion_payload(model: str, messages: list, *, max_tokens=256, stream=False, **extra):
    return {"model": model, "messages": messages, "max_tokens": max_tokens,
            "temperature": 0, "seed": 42, "reasoning_effort": "none", "stream": stream, **extra}


def answer_of(response: dict):
    choices = response.get("choices") or []
    if not choices:
        raise VerificationError("Completion contains no choices")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise VerificationError("Completion exhausted its output budget")
    return choice.get("message") or {}, choice.get("finish_reason")


def measures(response: dict, elapsed: float):
    usage, timing = response.get("usage") or {}, response.get("timings") or {}
    count = usage.get("completion_tokens")
    return {"elapsed_seconds": round(elapsed, 3), "usage": usage, "timings": timing,
            "decode_tokens_per_second": timing.get("predicted_per_second"),
            "end_to_end_output_tokens_per_second": round(count / elapsed, 3) if count and elapsed else None}


class Verifier:
    def __init__(self, args):
        self.args = args
        config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
        root = Path(config["target"]["root"]).resolve()
        if os.path.normcase(str(root)) != os.path.normcase(str(Path("C:/AI/LocalLLM").resolve())):
            raise VerificationError("Verification output root must be C:/AI/LocalLLM")
        tests = (root / "tests").resolve()
        if not tests.is_relative_to(root):
            raise VerificationError("Verification output path escapes LocalLLM")
        self.out = tests / ("20261006-strata-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        self.out.mkdir(parents=True, exist_ok=False)
        self.client = Client(args.url or config["target"]["defaultUrl"], args.timeout)
        self.results = []
        self.model = args.canonical

    def record(self, name, action):
        started = time.perf_counter()
        try:
            details = action()
            result = {"name": name, "passed": True, **details}
        except Exception as error:
            result = {"name": name, "passed": False, "error": str(error), "error_type": type(error).__name__}
        result.setdefault("elapsed_seconds", round(time.perf_counter() - started, 3))
        self.results.append(result)
        (self.out / (name + ".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"name": name, "passed": result["passed"], "elapsed_seconds": result["elapsed_seconds"],
                          "error": result.get("error")}, ensure_ascii=False), flush=True)
        return result["passed"]

    def completion(self, payload):
        self.client.idle_state()
        start = time.perf_counter()
        response = self.client.json("/v1/chat/completions", payload)
        elapsed = time.perf_counter() - start
        self.client.wait_idle()
        return response, measures(response, elapsed)

    def health_aliases(self):
        health = self.client.json("/health")
        expected = {"status": "ok", "service": "strata", "loaded": True,
                    "images": True, "max_context": self.args.expected_context, "model": self.model}
        if any(health.get(key) != value for key, value in expected.items()):
            raise VerificationError(f"Strata health does not match the prepared model: {health}")
        models = self.client.json("/v1/models")
        by_id = {item["id"]: item for item in models.get("data", [])}
        if self.model not in by_id or LEGACY_ALIAS not in by_id:
            raise VerificationError("Canonical and legacy model IDs are not both advertised")
        if by_id[LEGACY_ALIAS].get("alias_of") != self.model:
            raise VerificationError("Legacy alias does not identify the replacement model")
        for model in (self.model, LEGACY_ALIAS):
            item = by_id[model]
            if item.get("meta", {}).get("n_ctx") != self.args.expected_context or "image" not in item.get("architecture", {}).get("input_modalities", []):
                raise VerificationError(f"Advertised context/vision mismatch for {model}")
        props = self.client.json("/props")
        if props.get("default_generation_settings", {}).get("n_ctx") != self.args.expected_context:
            raise VerificationError("/props context does not match the health context")
        capabilities = self.client.json("/v1/status")
        if capabilities.get("structured_output", {}).get("method") != "prompt_and_validate":
            raise VerificationError("Strata structured output capability is missing")
        self.client.idle_state()
        return {"health": health, "models": models, "props": props, "capabilities": capabilities}

    def japanese_schema_alias(self):
        fmt = object_format("japanese_smoke", {"name": {"type": "string"}, "answer": {"type": "integer"}})
        request = completion_payload(LEGACY_ALIAS, [{"role": "user", "content":
            "名前はカタカナの『リダ』だけ、answerは17×19の計算結果です。指定されたJSONだけで回答してください。"}], response_format=fmt)
        response, metrics = self.completion(request)
        message, finish = answer_of(response)
        answer = json.loads(message.get("content") or "")
        if answer != {"name": "リダ", "answer": 323} or response.get("model") != LEGACY_ALIAS or finish != "stop":
            raise VerificationError(f"Japanese JSON or legacy response model mismatch: {answer}")
        return {"answer": answer, "response": response, **metrics}

    def vision(self, swapped):
        name = "vision_swapped" if swapped else "vision"
        path = self.out / (name + ".png")
        png_fixture(path, swapped)
        fmt = object_format(name, {side: {"type": "string", "enum": ["赤い円", "青い正方形"]} for side in ("left", "right")})
        content = [{"type": "text", "text": "この画像だけを見て、左側の図形をleft、右側の図形をrightに記入してください。色と形の両方を読み取り、指定されたJSONだけで回答してください。"},
                   {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")}}]
        response, metrics = self.completion(completion_payload(self.model, [{"role": "user", "content": content}], response_format=fmt))
        message, _ = answer_of(response)
        answer = json.loads(message.get("content") or "")
        expected = {"left": "青い正方形", "right": "赤い円"} if swapped else {"left": "赤い円", "right": "青い正方形"}
        if answer != expected:
            raise VerificationError(f"Vision positions/colors/shapes mismatch: {answer}; expected {expected}")
        return {"fixture": str(path), "expected": expected, "answer": answer, "response": response, **metrics}

    def tool_loop(self):
        fixture = self.out / "dummy-tool-note.txt"
        fixture.write_text("STRATA_FIXTURE_OK\n", encoding="utf-8")
        tools = [{"type": "function", "function": {"name": "read_fixture", "description": "テスト用メモsmoke-noteの内容だけを読みます。",
                 "parameters": {"type": "object", "properties": {"asset": {"type": "string", "enum": ["smoke-note"]}}, "required": ["asset"], "additionalProperties": False}}},
                 {"type": "function", "function": {"name": "add_numbers", "description": "2個の整数を安全に足します。",
                 "parameters": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"], "additionalProperties": False}}}]
        messages = [{"role": "user", "content": "必ずread_fixtureでsmoke-noteを読み、add_numbersで17と19を足してください。両方のツール結果を受け取った後、fixtureにメモの文字列（末尾改行を除く）、sumに足した数を入れたJSONだけを返してください。"}]
        calls_seen, rounds = set(), []
        for _ in range(6):
            response, metrics = self.completion(completion_payload(self.model, messages, tools=tools, max_tokens=512))
            message, finish = answer_of(response)
            rounds.append({"response": response, **metrics})
            calls = message.get("tool_calls") or []
            if not calls:
                answer = json.loads(message.get("content") or "")
                if calls_seen != {"read_fixture", "add_numbers"} or answer != {"fixture": "STRATA_FIXTURE_OK", "sum": 36}:
                    raise VerificationError(f"Tool execution/results were not reflected in the final answer: {answer}, {sorted(calls_seen)}")
                return {"answer": answer, "calls_seen": sorted(calls_seen), "rounds": rounds,
                        "elapsed_seconds": round(sum(r["elapsed_seconds"] for r in rounds), 3)}
            if finish != "tool_calls":
                raise VerificationError("Tool call response does not finish with tool_calls")
            messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
            for call in calls:
                function = call.get("function") or {}
                name = function.get("name")
                arguments = json.loads(function.get("arguments") or "{}")
                if name == "read_fixture" and arguments == {"asset": "smoke-note"}:
                    result = {"text": fixture.read_text(encoding="utf-8").strip()}
                elif name == "add_numbers" and set(arguments) == {"a", "b"} and all(type(arguments[k]) is int and abs(arguments[k]) <= 1000000 for k in ("a", "b")):
                    result = {"sum": arguments["a"] + arguments["b"]}
                else:
                    raise VerificationError(f"Refused unexpected dummy tool name/arguments: {name}, {arguments}")
                calls_seen.add(name)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
        raise VerificationError("Tool loop did not finish within six rounds")

    def stream_text(self):
        self.client.idle_state()
        request = completion_payload(self.model, [{"role": "user", "content": "STREAM_OK という文字列だけをそのまま出力してください。"}], max_tokens=128, stream=True)
        start = time.perf_counter()
        connection, owned_socket, response = self.client.open("/v1/chat/completions", request)
        chunks, content, done, finish, first = [], "", False, None, None
        try:
            for line in response:
                line = line.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    done = True
                    break
                chunk = json.loads(data)
                if "error" in chunk:
                    raise VerificationError(f"SSE error: {chunk['error']}")
                chunks.append(chunk)
                for choice in chunk.get("choices") or []:
                    text = choice.get("delta", {}).get("content") or ""
                    if text and first is None:
                        first = time.perf_counter() - start
                    content += text
                    finish = choice.get("finish_reason") or finish
        finally:
            response.close()
            connection.close()
            owned_socket.close()
        elapsed = time.perf_counter() - start
        self.client.wait_idle()
        if content.strip() != "STREAM_OK" or not done or finish != "stop":
            raise VerificationError(f"Text SSE did not finish correctly: {content!r}, DONE={done}, finish={finish}")
        metrics_source = next((chunk for chunk in reversed(chunks) if chunk.get("usage")), {})
        return {"answer": content, "done": done, "finish_reason": finish, "chunks": chunks,
                "first_content_seconds": round(first, 3) if first is not None else None, **measures(metrics_source, elapsed)}

    def long_context(self):
        sentinel = "STRATA_" + self.out.name.rsplit("-", 1)[-1] + "_見つけた"
        line_count, counts = 650, []
        for _ in range(5):
            lines = [f"ROW {i:05d}: alpha beta gamma delta epsilon. 木曜日の記録は正常です。\n" for i in range(line_count)]
            lines.insert(line_count // 3, "指定の照合値 LONG_CONTEXT_TARGET = " + sentinel + "\n")
            prompt = "以下は架空の検査資料です。資料内のLONG_CONTEXT_TARGETの値を正確に読み取ってください。\n" + "".join(lines) + "\nLONG_CONTEXT_TARGETの値だけをanswerに入れ、指定されたJSONを返してください。"
            count = self.client.json("/v1/messages/count_tokens", {"model": self.model, "messages": [{"role": "user", "content": prompt}], "thinking": {"type": "disabled"}, "max_tokens": 128})
            tokens = count.get("input_tokens")
            if type(tokens) is not int or tokens <= 0:
                raise VerificationError("Strata did not provide a usable exact token count")
            counts.append({"lines": line_count, "input_tokens": tokens})
            if tokens >= 12000:
                break
            line_count = int(line_count * 12000 / tokens) + 50
        else:
            raise VerificationError("Controlled context did not reach 12000 tokens")
        if tokens + 512 >= self.args.expected_context:
            raise VerificationError("Controlled context would exceed the prepared model's context")
        (self.out / "long-context-fixture.txt").write_text(prompt, encoding="utf-8")
        response, metrics = self.completion(completion_payload(self.model, [{"role": "user", "content": prompt}], max_tokens=128,
            response_format=object_format("long_context", {"answer": {"type": "string"}})))
        message, _ = answer_of(response)
        answer = json.loads(message.get("content") or "")
        if answer != {"answer": sentinel}:
            raise VerificationError(f"Long context exact retrieval failed: {answer}")
        if (response.get("usage") or {}).get("prompt_tokens", 0) < 12000:
            raise VerificationError("Actual completion prompt was not above 12000 tokens")
        return {"answer": answer, "expected": sentinel, "exact_input_count": counts,
                "fixture": str(self.out / "long-context-fixture.txt"), "response": response, **metrics}

    def cancel_own_request(self):
        before = self.client.idle_state()  # Busy/unknown fails before sending anything cancellable.
        request = completion_payload(self.model, [{"role": "user", "content":
            "00001から10000までの連番を、1行に1番号ずつ、途中を省略せずに出力してください。説明やコードは不要です。"}], max_tokens=4096, stream=True)
        start = time.perf_counter()
        connection, owned_socket, response = self.client.open("/v1/chat/completions", request)
        content, closed_early, done = "", False, False
        try:
            for line in response:
                line = line.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    done = True
                    break
                chunk = json.loads(data)
                if "error" in chunk:
                    raise VerificationError(f"SSE error before cancellation: {chunk['error']}")
                for choice in chunk.get("choices") or []:
                    content += choice.get("delta", {}).get("content") or ""
                if len(content) >= 24:
                    # Retain the actual connection socket even for HTTP/1.0, where
                    # HTTPConnection.getresponse may clear connection.sock.
                    owned_socket.shutdown(socket.SHUT_RDWR)
                    owned_socket.close()
                    closed_early = True
                    break
        finally:
            response.close()
            connection.close()
            owned_socket.close()
        if not closed_early or done:
            raise VerificationError("Request finished before a controlled disconnect could be tested")
        disconnect_at = time.perf_counter()
        after = self.client.wait_idle(timeout=90)
        idle_after_seconds = time.perf_counter() - disconnect_at
        recovery, metrics = self.completion(completion_payload(self.model, [{"role": "user", "content": "CANCEL_RECOVERED という文字列だけをそのまま出力してください。"}], max_tokens=64))
        message, finish = answer_of(recovery)
        if (message.get("content") or "").strip() != "CANCEL_RECOVERED" or finish != "stop":
            raise VerificationError("The model did not recover correctly after the owned request was disconnected")
        return {"precondition": before, "owned_request_prefix": content, "disconnected_before_DONE": True,
                "seconds_before_disconnect": round(disconnect_at - start, 3), "idle_after_seconds": round(idle_after_seconds, 3),
                "after": after, "recovery_response": recovery, "recovery_metrics": metrics,
                "elapsed_seconds": round(time.perf_counter() - start, 3)}

    def run(self):
        phases = {"smoke": [("japanese_schema_alias", self.japanese_schema_alias), ("vision", lambda: self.vision(False)),
                            ("vision_swapped", lambda: self.vision(True)), ("tool_loop", self.tool_loop), ("stream_text", self.stream_text)],
                  "long": [("long_context", self.long_context)], "cancel": [("cancel", self.cancel_own_request)]}
        selected = ["smoke", "long", "cancel"] if self.args.phase == "all" else [self.args.phase]
        planned = [("health_aliases", self.health_aliases)] + [case for phase in selected for case in phases[phase]]
        if self.record(*planned[0]):
            for name, action in planned[1:]:
                self.record(name, action)
        summary = {"passed": len(self.results) == len(planned) and all(result["passed"] for result in self.results),
                   "phase": self.args.phase, "expected_context": self.args.expected_context,
                   "canonical_model": self.model, "legacy_alias": LEGACY_ALIAS,
                   "checks": {result["name"]: result["passed"] for result in self.results},
                   "results": self.results, "result_directory": str(self.out),
                   "scope": "Synthetic fixtures only; local HTTP text/vision/tools/schema/SSE/context/cancellation. Open WebUI and MCP require separate verification.",
                   "finished_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        (self.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: summary[key] for key in ("passed", "phase", "checks", "result_directory")}, ensure_ascii=False), flush=True)
        return 0 if summary["passed"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("smoke", "long", "cancel", "all"), default="smoke")
    parser.add_argument("--config", default=str(SUPPORTER / "config/support-config.json"))
    parser.add_argument("--url", help="Override the local base URL for an isolated test server")
    parser.add_argument("--canonical", default=CANONICAL)
    parser.add_argument("--expected-context", type=int, default=131072)
    parser.add_argument("--timeout", type=float, default=360)
    args = parser.parse_args(argv)
    if args.expected_context < 16384 or not 1 <= args.timeout <= 600:
        parser.error("Use a context >=16384 and an HTTP timeout between 1 and 600 seconds")
    return Verifier(args).run()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"passed": False, "error": str(error), "error_type": type(error).__name__}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
