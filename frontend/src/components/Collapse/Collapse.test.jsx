// @vitest-environment happy-dom
import { act, createRef } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test } from "vitest";

import Collapse from "./Collapse";

let root;
let host;

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

describe("Collapse", () => {
  test("keeps the content mounted, inert while closed, and forwards id and ref", () => {
    const ref = createRef();
    act(() => {
      root.render(<Collapse ref={ref} id="list" open={false}><button type="button">Approve</button></Collapse>);
    });
    const box = host.querySelector("#list");
    expect(ref.current).toBe(box);
    expect(box.hasAttribute("inert")).toBe(true);
    expect(box.querySelector("button")).toBeTruthy();

    act(() => {
      root.render(<Collapse ref={ref} id="list" open><button type="button">Approve</button></Collapse>);
    });
    expect(box.hasAttribute("inert")).toBe(false);
  });

  test("passes the surrounding gap as a CSS variable only when given", () => {
    act(() => { root.render(<Collapse id="a" open gap={16}>x</Collapse>); });
    expect(host.querySelector("#a").style.getPropertyValue("--collapse-gap")).toBe("16px");

    act(() => { root.render(<Collapse id="a" open>x</Collapse>); });
    expect(host.querySelector("#a").style.getPropertyValue("--collapse-gap")).toBe("");
  });
});
