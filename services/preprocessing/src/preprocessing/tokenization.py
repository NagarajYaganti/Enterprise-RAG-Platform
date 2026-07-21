import tiktoken

# Shared across FixedSizeChunker (token-based chunk sizing) and
# ChunkingPolicy (doc_length_tokens/heading_density signals) so both use
# the exact same token-counting proxy rather than two separate encoding
# instances. See fixed_size.py's module docstring for why cl100k_base
# specifically (a lightweight, no-torch proxy, not the embedding model's
# own tokenizer).
_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def encode(text: str) -> list[int]:
    return _ENCODING.encode(text)


def decode(tokens: list[int]) -> str:
    return _ENCODING.decode(tokens)
