export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const apiKey = (process.env.SILICONFLOW_API_KEY || '').trim();
  const apiUrl = (process.env.LLM_API_URL || '').trim() || 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions';
  const llmModel = (process.env.LLM_MODEL || '').trim() || 'qwen-plus';
  const timeoutMs = Number.parseInt((process.env.API_TIMEOUT || '120').trim(), 10) * 1000;

  if (!apiKey) {
    return res.status(500).json({ error: 'Missing SILICONFLOW_API_KEY in Vercel environment' });
  }

  const incoming = req.body && typeof req.body === 'object' ? req.body : null;
  if (!incoming) {
    return res.status(400).json({ error: 'Invalid JSON payload' });
  }

  const payload = { ...incoming, model: incoming.model || llmModel };

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(timeoutMs, 1000));

  try {
    const upstream = await fetch(apiUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    const text = await upstream.text();
    const contentType = upstream.headers.get('content-type') || 'application/json; charset=utf-8';
    res.setHeader('Content-Type', contentType);
    return res.status(upstream.status).send(text);
  } catch (err) {
    const detail = err && err.name === 'AbortError' ? 'Upstream request timeout' : String(err);
    return res.status(502).json({ error: 'Upstream request failed', detail });
  } finally {
    clearTimeout(timer);
  }
}
