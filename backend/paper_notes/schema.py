"""筆記區塊的資料模型（note.json 的唯一定義）。"""
from typing import Annotated, Literal, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator


def new_id() -> str:
    return uuid4().hex[:10]


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    widthPct: float = Field(100, ge=10, le=100)
    heightPx: int | None = Field(None, ge=50, le=2000)
    marginTopPx: int = Field(8, ge=0, le=200)
    marginBottomPx: int = Field(8, ge=0, le=200)
    align: Literal["left", "center", "right"] = "center"


class _Block(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=new_id, min_length=1)
    layout: Layout | None = None


class Heading(_Block):
    type: Literal["heading"]
    level: int = Field(ge=1, le=3)
    text: str


class Paragraph(_Block):
    type: Literal["paragraph"]
    text: str


class Eli5(_Block):
    type: Literal["eli5"]
    text: str


_VEGA_VIEW_KEYS = {"mark", "layer", "concat", "hconcat", "vconcat", "facet", "repeat"}


class Chart(_Block):
    type: Literal["chart"]
    spec: dict
    source: str = ""
    verified: bool = False

    @field_validator("spec")
    @classmethod
    def _spec_has_view(cls, v: dict) -> dict:
        if not _VEGA_VIEW_KEYS & v.keys():
            raise ValueError("Vega-Lite spec 需要 mark/layer/concat 等其中一個欄位")
        return v


class Diagram(_Block):
    type: Literal["diagram"]
    mermaid: str = Field(min_length=1)


class Figure(_Block):
    type: Literal["figure"]
    path: str = Field(pattern=r"^[\w.-]+\.png$")
    caption: str = ""
    page: int = Field(ge=1)


class Whiteboard(_Block):
    type: Literal["whiteboard"]
    scene: dict = Field(default_factory=lambda: {"elements": []})


LeafBlock = Annotated[
    Union[Heading, Paragraph, Eli5, Chart, Diagram, Figure, Whiteboard],
    Field(discriminator="type"),
]


class Column(BaseModel):
    model_config = ConfigDict(extra="forbid")
    widthPct: float = Field(ge=10, le=90)
    blocks: list[LeafBlock] = Field(min_length=1)


class Columns(_Block):
    type: Literal["columns"]
    columns: list[Column] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def _widths_sum_to_100(self):
        total = sum(c.widthPct for c in self.columns)
        if abs(total - 100) > 1:
            raise ValueError(f"欄寬總和必須是 100，目前是 {total}")
        return self


Block = Annotated[
    Union[Heading, Paragraph, Eli5, Chart, Diagram, Figure, Whiteboard, Columns],
    Field(discriminator="type"),
]


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blocks: list[Block]


BlockList = TypeAdapter(list[Block])


def flatten(blocks: list) -> list:
    """依文件順序攤平；columns 本身與其內部區塊都列入。"""
    out = []
    for b in blocks:
        out.append(b)
        if b.type == "columns":
            for col in b.columns:
                out.extend(col.blocks)
    return out
