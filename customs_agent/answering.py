import os

from customs_agent.prompts import CUSTOMS_BROKER_SYSTEM_PROMPT


NO_EVIDENCE = "未在已入库的报关单中找到相关信息。"


def _evidence_fallback(evidence: list[dict], prefix: str = "已找到以下相关原文") -> str:
    snippets = "\n\n".join(
        f"[{i + 1}] {item['filename']}：{item['content'][:420]}" for i, item in enumerate(evidence[:3])
    )
    return f"{prefix}：\n\n{snippets}"


def answer(question: str, evidence: list[dict]) -> tuple[str, str]:
    if not evidence:
        return NO_EVIDENCE, "none"
    api_key = (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")).strip()
    if not api_key:
        return _evidence_fallback(evidence, "已找到以下相关原文（未配置模型，故不做推断）"), "retrieval-only"

    from openai import OpenAI
    evidence = evidence[:3]
    context = "\n\n".join(
        f"证据[{i + 1}] 文件={item['filename']} 分块={item['chunk_index']}\n{item['content'][:1200]}"
        for i, item in enumerate(evidence)
    )
    prompt = f"""用户问题：{question}

检索证据：
{context}"""
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip()
    model = (os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5")).strip()
    mode = os.getenv("LLM_API_MODE", "responses").strip().lower()
    timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "12"))
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
    try:
        if mode == "chat_completions":
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": CUSTOMS_BROKER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
            )
            content = response.choices[0].message.content or ""
            return content.strip(), "openai-compatible-chat"
        response = client.responses.create(
            model=model, instructions=CUSTOMS_BROKER_SYSTEM_PROMPT, input=prompt,
            store=False, max_output_tokens=300,
        )
        return response.output_text.strip(), "openai-responses"
    except Exception:
        return _evidence_fallback(evidence, "模型响应超时或暂时不可用，已自动返回相关原文"), "retrieval-fallback"
