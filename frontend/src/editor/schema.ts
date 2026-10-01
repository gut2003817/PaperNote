import { BlockNoteSchema, defaultBlockSpecs } from "@blocknote/core";
import { withMultiColumn } from "@blocknote/xl-multi-column";
import { ChartBlock, DiagramBlock, Eli5Block, FigureBlock, WhiteboardBlock } from "./blocks";

const { paragraph, heading } = defaultBlockSpecs;

/** 只開放筆記 schema 支援的區塊；斜線選單會依此自動過濾內建選項。 */
export const schema = withMultiColumn(
  BlockNoteSchema.create({
    blockSpecs: {
      paragraph,
      heading,
      eli5: Eli5Block(),
      chart: ChartBlock(),
      diagram: DiagramBlock(),
      figure: FigureBlock(),
      whiteboard: WhiteboardBlock(),
    },
  }),
);
