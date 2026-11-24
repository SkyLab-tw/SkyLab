// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { ReactFlowProvider } from "@xyflow/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ConnectionEdge from "./ConnectionEdge";

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal()),
  useTranslation: () => ({ t: (key) => key, i18n: { language: "zh-TW" } }),
}));

let host;
let root;

const mainPath = () => host.querySelector("path.react-flow__edge-path");
const hitPath = () => host.querySelector('path[stroke="transparent"]');

function pointer(type, pointerType) {
  act(() => {
    hitPath().dispatchEvent(new PointerEvent(type, { bubbles: true, pointerType }));
  });
}

describe("ConnectionEdge 滑過", () => {
  beforeEach(async () => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => {
      root.render(
        <ReactFlowProvider>
          <svg>
            <ConnectionEdge
              id="e1"
              sourceX={0}
              sourceY={0}
              targetX={240}
              targetY={0}
              sourcePosition="right"
              targetPosition="left"
              data={{ edge: { source_vmid: 1, target_vmid: 2, direction: "forward" }, label: "TCP 22", onSelect: vi.fn() }}
            />
          </svg>
        </ReactFlowProvider>,
      );
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  /* iOS 點下去時若 hover 讓隱藏的標籤浮出來，第一下只會被當成 hover，要點兩下才選得到線 */
  it("觸控不算滑過，線維持原樣", () => {
    pointer("pointerover", "touch");
    expect(mainPath().style.strokeWidth).toBe("1.8");
  });

  it("滑鼠滑過才加粗，移開恢復", () => {
    pointer("pointerover", "mouse");
    expect(mainPath().style.strokeWidth).toBe("2.5");
    pointer("pointerout", "mouse");
    expect(mainPath().style.strokeWidth).toBe("1.8");
  });
});
