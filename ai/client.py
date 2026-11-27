"""Claude 호출은 모두 이 모듈을 거친다 (모델·오류 처리·비용 관리를 한곳에서)"""

import json

import anthropic

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key)


def stream_reply(api_key: str, messages: list, system: str, effort: str = "high"):
    """대화 응답을 텍스트 조각으로 흘려보냄 (st.write_stream 용).
    messages: [{"role": "user"|"assistant", "content": str}, ...]
    """
    client = _client(api_key)
    try:
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=16000,
            system=system,
            messages=messages,
            output_config={"effort": effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            for text in stream.text_stream:
                yield text
            final = stream.get_final_message()
            if final.stop_reason == "refusal":
                yield "\n\n⚠️ 이 요청은 모델이 응답을 거절했습니다. 표현을 바꿔 다시 시도해 주세요."
            elif final.stop_reason == "max_tokens":
                yield "\n\n⚠️ 답변이 길이 제한으로 잘렸습니다. '이어서 써 줘'라고 보내 주세요."
    except anthropic.AuthenticationError:
        yield "❌ API 키가 올바르지 않습니다. 사이드바에서 확인해 주세요."
    except anthropic.RateLimitError:
        yield "❌ 요청이 많아 잠시 막혔습니다. 1분쯤 뒤에 다시 시도해 주세요."
    except anthropic.APIStatusError as e:
        yield f"❌ API 오류 ({e.status_code}): {e.message}"
    except anthropic.APIConnectionError:
        yield "❌ 네트워크 연결 오류입니다. 잠시 뒤 다시 시도해 주세요."


def extract_fields(api_key: str, text: str, fields: list, extra_schema: dict | None = None) -> dict:
    """코칭 결과 본문에서 출력 형식 항목을 JSON 으로 뽑아냄 (구조화 출력).
    extra_schema: {"필드명": {"type": ..., "description": ...}} 추가 필드
    """
    props = {f: {"type": "string", "description": f"'{f}' 항목의 내용. 본문에 없으면 빈 문자열"} for f in fields}
    if extra_schema:
        props.update(extra_schema)
    schema = {
        "type": "object",
        "properties": props,
        "required": list(props.keys()),
        "additionalProperties": False,
    }
    client = _client(api_key)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        messages=[{
            "role": "user",
            "content": "다음 코칭 결과에서 각 항목의 내용을 본문 표현 그대로 옮겨 주세요. "
                       "본문에 없는 내용은 지어내지 말고 빈 값으로 두세요.\n\n<코칭 결과>\n" + text + "\n</코칭 결과>",
        }],
    )
    if resp.stop_reason == "refusal":
        return {}
    raw = next((b.text for b in resp.content if b.type == "text"), "{}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}
