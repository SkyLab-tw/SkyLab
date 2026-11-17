// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import SegmentedControl from "./SegmentedControl";

vi.mock("../MIcon", () => ({ default: ({ name }) => <i data-icon={name} /> }));

const OPTIONS = [
  { value: "7d", label: "7 天" },
  { value: "30d", label: "30 天", badge: 2 },
  { value: "90d", label: "90 天", buttonProps: { disabled: true } },
];

let host;
let root;

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

const buttons = () => [...host.querySelectorAll("button")];

describe("SegmentedControl", () => {
  test("群組名稱、選中段 aria-pressed，點擊回傳 value，停用段不觸發", () => {
    const onChange = vi.fn();
    act(() => root.render(<SegmentedControl options={OPTIONS} value="30d" onChange={onChange} ariaLabel="日期區間" />));

    expect(host.querySelector('[role="group"]').getAttribute("aria-label")).toBe("日期區間");
    expect(buttons().map((button) => button.getAttribute("aria-pressed"))).toEqual(["false", "true", "false"]);
    expect(buttons()[1].textContent).toBe("30 天2");

    act(() => buttons()[0].click());
    act(() => buttons()[2].click());
    expect(onChange.mock.calls).toEqual([["7d"]]);
  });

  test("quiet 只加輕量版類名，行為不變；預設不帶", () => {
    act(() => root.render(<SegmentedControl options={OPTIONS} value="7d" onChange={() => {}} ariaLabel="日期區間" />));
    expect(host.querySelector('[role="group"]').className).not.toMatch(/segmentQuiet/);

    act(() => root.render(<SegmentedControl quiet options={OPTIONS} value="7d" onChange={() => {}} ariaLabel="日期區間" />));
    expect(host.querySelector('[role="group"]').className).toMatch(/segmentQuiet/);
    expect(buttons()[0].getAttribute("aria-pressed")).toBe("true");
  });
});
