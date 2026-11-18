// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { ReactFlowProvider } from "@xyflow/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useEarlierLabelRects, usePublishLabelRect } from "./labelRegistry";

let host;
let root;

/* 一條線的標籤：登記自己的範圍，並回報看得到哪些排在前面的標籤 */
function Label({ id, rank, rect, seen }) {
  seen[id] = useEarlierLabelRects(id, rank);
  usePublishLabelRect(id, rank, rect);
  return null;
}

function render(children) {
  act(() => {
    root.render(children);
  });
}

describe("labelRegistry", () => {
  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  /* 曾經每條線各拿到一份登記表（useStoreApi 每次都包一個新物件當 key），標籤彼此看不到而疊在一起 */
  it("同一張畫布的標籤共用一份登記表，後排的看得到前面的", () => {
    const seen = {};
    const first = { x: 10, y: 20, w: 100, h: 20 };
    const second = { x: 200, y: 20, w: 80, h: 20 };
    render(
      <ReactFlowProvider>
        <Label key="a" id="a" rank={0} rect={first} seen={seen} />
        <Label key="b" id="b" rank={1} rect={second} seen={seen} />
      </ReactFlowProvider>,
    );

    expect(seen.b).toEqual([first]);
    /* 前面的不看後面的，才不會互相推來推去 */
    expect(seen.a).toEqual([]);
  });

  it("線拿掉後撤掉登記，後面的標籤不再避開那塊空地", () => {
    const seen = {};
    const first = { x: 10, y: 20, w: 100, h: 20 };
    render(
      <ReactFlowProvider>
        <Label key="a" id="a" rank={0} rect={first} seen={seen} />
        <Label key="b" id="b" rank={1} rect={null} seen={seen} />
      </ReactFlowProvider>,
    );
    expect(seen.b).toEqual([first]);

    render(
      <ReactFlowProvider>
        <Label key="b" id="b" rank={1} rect={null} seen={seen} />
      </ReactFlowProvider>,
    );
    expect(seen.b).toEqual([]);
  });

  it("不同畫布各自一份，不會互相避開", () => {
    const seen = {};
    render(
      <>
        <ReactFlowProvider>
          <Label key="a" id="a" rank={0} rect={{ x: 0, y: 0, w: 50, h: 20 }} seen={seen} />
        </ReactFlowProvider>
        <ReactFlowProvider>
          <Label key="b" id="b" rank={1} rect={null} seen={seen} />
        </ReactFlowProvider>
      </>,
    );

    expect(seen.b).toEqual([]);
  });
});
