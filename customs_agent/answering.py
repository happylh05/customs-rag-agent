import os

from customs_agent.prompts import CUSTOMS_BROKER_SYSTEM_PROMPT


NO_EVIDENCE = "未在已入库的报关单中找到相关信息。"


def answer(question: str, evidence: list[dict]) -> tuple[str, str]:
    if not evidence:
        return NO_EVIDENCE, "none"
    api_key = (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")).strip()
    if not api_key:
        snippets = "\n\n".join(
            f"[{i + 1}] {item['filename']}：{item['content'][:500]}" for i, item in enumerate(evidence)
        )
        return f"已找到以下相关原文（未配置模型，故不做推断）：\n\n{snippets}", "retrieval-only"

    from openai import OpenAI
    context = "\n\n".join(
        f"证据[{i + 1}] 文件={item['filename']} 分块={item['chunk_index']}\n{item['content']}"
        for i, item in enumerate(evidence)
    )
    prompt = f"""用户问题：{question}

检索证据：
{context}"""
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip()
    model = (os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5")).strip()
    mode = os.getenv("LLM_API_MODE", "responses").strip().lower()
    client = OpenAI(api_key=api_key, base_url=base_url)
    if mode == "chat_completions":
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": CUSTOMS_BROKER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or ""
        return content.strip(), "openai-compatible-chat"
    response = client.responses.create(
        model=model, instructions=CUSTOMS_BROKER_SYSTEM_PROMPT, input=prompt, store=False
    )
    return response.output_text.strip(), "openai-responses"
