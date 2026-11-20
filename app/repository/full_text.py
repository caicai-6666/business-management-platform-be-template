"""FTS5 索引与字面短语查询使用同一套中文切分。"""
import re

_HAN = re.compile(r"[㐀-鿿𠀀-𯨟]")


def index_text(value: str) -> str:
    separated = _HAN.sub(r" \g<0> ", value.casefold())
    return " ".join(re.findall(r"[^\W_]+", separated))


def match_phrase(value: str) -> str:
    return '"' + index_text(value) + '"'
