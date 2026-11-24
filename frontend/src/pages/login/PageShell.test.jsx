// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useOctoMood, useOctoScene } from "./octoMood";
import PageShell from "./PageShell";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key) => key }) }));
vi.mock("../../components/OctoPet/OctoPet", () => ({
  default: ({ activity }) => <i data-testid="octo" data-activity={activity} />,
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let host;
let root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const bubble = () => host.querySelector('p[aria-hidden="true"]').textContent;
const octo = () => host.querySelector('[data-testid="octo"]').dataset.activity;

function Probe({ scene }) {
  const { setMood } = useOctoMood();
  useOctoScene(scene);
  return (
    <button type="button" data-testid="fail" onClick={() => setMood("error")}>
      body
    </button>
  );
}

test("內容放在卡片裡，章魚照 scene 打招呼", async () => {
  await act(async () => root.render(<PageShell scene="enroll">body</PageShell>));
  expect(host.querySelector("main").textContent).toBe("body");
  expect(bubble()).toBe("PixelLogin.say.enroll");
  expect(octo()).toBe("idle");
});

test("wide 只多加一個版面修飾類", async () => {
  await act(async () => root.render(<PageShell>body</PageShell>));
  const narrow = host.querySelector("main").parentElement.className;
  await act(async () => root.render(<PageShell wide>body</PageShell>));
  const wide = host.querySelector("main").parentElement.className;
  expect(wide.startsWith(narrow)).toBe(true);
  expect(wide.split(" ")).toHaveLength(narrow.split(" ").length + 1);
});

test("裡面的畫面回報心情與換畫面：出錯換台詞，換畫面後心情歸零", async () => {
  await act(async () => root.render(<PageShell><Probe scene="forgot" /></PageShell>));
  expect(bubble()).toBe("PixelLogin.say.forgot");

  await act(async () => host.querySelector('[data-testid="fail"]').click());
  expect(bubble()).toBe("PixelLogin.say.error");
  expect(octo()).toBe("error");

  await act(async () => root.render(<PageShell><Probe scene="reset" /></PageShell>));
  expect(bubble()).toBe("PixelLogin.say.reset");
  expect(octo()).toBe("idle");
});

test("戳章魚：借用成功的動作，輪流說三句話", async () => {
  await act(async () => root.render(<PageShell>body</PageShell>));
  const button = host.querySelector('button[aria-label="PixelLogin.octoLabel"]');
  const lines = [];
  for (let i = 0; i < 4; i += 1) {
    await act(async () => button.click());
    lines.push(bubble());
  }
  expect(octo()).toBe("done");
  expect(lines).toEqual(["PixelLogin.poke.0", "PixelLogin.poke.1", "PixelLogin.poke.2", "PixelLogin.poke.0"]);
});
