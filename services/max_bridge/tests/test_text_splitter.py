from app.text_splitter import SAFE_LIMIT, split_for_max


def test_short_text_returns_single_chunk():
    text = "Привет, бот."
    assert split_for_max(text) == [text]


def test_empty_returns_empty_list():
    assert split_for_max("") == []
    assert split_for_max("    ") == []
    assert split_for_max(None) == []


def test_paragraph_packing_under_limit():
    paragraphs = [f"Параграф {i} " * 5 for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = split_for_max(text, limit=200)
    assert all(len(c) <= 200 for c in chunks)
    # Round-tripping should preserve all original information modulo whitespace.
    joined = " ".join(chunks)
    for p in paragraphs:
        assert p.strip()[:20] in joined


def test_oversized_paragraph_falls_back_to_sentences():
    sentence = "Это короткое предложение. "
    big_paragraph = sentence * 200  # ~5000 chars
    chunks = split_for_max(big_paragraph, limit=200)
    assert chunks, "splitter must produce at least one chunk"
    assert all(len(c) <= 200 for c in chunks)


def test_pathological_run_is_hard_split():
    text = "x" * 10_000
    chunks = split_for_max(text, limit=500)
    assert all(len(c) <= 500 for c in chunks)
    assert sum(len(c) for c in chunks) == len(text)


def test_limit_default_matches_max_safe_envelope():
    text = "слово " * 1500
    chunks = split_for_max(text)
    assert all(len(c) <= SAFE_LIMIT for c in chunks)
