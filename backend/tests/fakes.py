class FakeRun:
    """取代 ai_runner.run：依序回傳 outputs，記錄每次的 prompt。"""

    def __init__(self, outputs: list):
        self.outputs = list(outputs)
        self.prompts: list[str] = []
        self.engines: list[str] = []

    def __call__(self, engine, prompt, schema, workdir, timeout=300):
        self.prompts.append(prompt)
        self.engines.append(engine)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out
