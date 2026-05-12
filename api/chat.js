module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  const apiKey = process.env.SILICONFLOW_API_KEY;
  if (!apiKey) {
    res.status(500).json({ error: "Missing SILICONFLOW_API_KEY" });
    return;
  }

  const upstreamUrl = process.env.LLM_API_URL || "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions";
  const model = process.env.LLM_MODEL || "qwen-plus";
  const timeoutMs = (parseInt(process.env.API_TIMEOUT || "120", 10) || 120) * 1000;

  try {
    const incoming = req.body && typeof req.body === "object" ? req.body : {};
    const payload = { ...incoming };
    if (!payload.model) {
      payload.model = model;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    const upstreamResp = await fetch(upstreamUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    clearTimeout(timer);

    const text = await upstreamResp.text();
    res.status(upstreamResp.status);
    res.setHeader("Content-Type", upstreamResp.headers.get("content-type") || "application/json; charset=utf-8");
    res.send(text);
  } catch (error) {
    const isTimeout = error && (error.name === "AbortError" || /aborted|timeout/i.test(String(error.message || "")));
    res.status(isTimeout ? 504 : 500).json({
      error: isTimeout ? "Upstream timeout" : "Upstream relay failed",
      detail: String(error && error.message ? error.message : error),
    });
  }
};
