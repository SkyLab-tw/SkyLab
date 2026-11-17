import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import ConnectionDetailPanel from "./ConnectionDetailPanel";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key) => key }),
}));

const baseEdge = {
  source_vmid: 101,
  target_vmid: 102,
  direction: "one_way",
  ports: [{ port: 0, protocol: "icmp" }],
};

function render(edge) {
  return renderToStaticMarkup(
    <ConnectionDetailPanel
      edge={edge}
      resolveName={(vmid) => `vm-${vmid}`}
      onClose={() => {}}
      onDelete={() => {}}
    />,
  );
}

describe("ConnectionDetailPanel managed topology", () => {
  it("marks template-managed edges and hides the delete action", () => {
    const html = render({ ...baseEdge, topology_managed: true });

    expect(html).toContain("ConnectionPanel.topologyManaged");
    expect(html).not.toContain("ConnectionPanel.delete");
  });

  it("keeps the delete action for regular firewall edges", () => {
    const html = render(baseEdge);

    expect(html).not.toContain("ConnectionPanel.topologyManaged");
    expect(html).toContain("ConnectionPanel.delete");
  });
});

describe("ConnectionDetailPanel ports", () => {
  /* 標籤換成 |，看得出哪幾段字是分開的兩行 */
  const text = (html) => html.replace(/(<[^>]+>)+/g, "|");
  const inbound = (ports) => renderToStaticMarkup(
    <ConnectionDetailPanel
      edge={{ source_vmid: null, target_vmid: 150, direction: "one_way", ports }}
      resolveName={(vmid) => (vmid === null ? "internet" : `vm-${vmid}`)}
      onClose={() => {}}
    />,
  );

  it("shows which port a published URL forwards to, not just the domain", () => {
    const html = text(inbound([{ port: 5678, protocol: "tcp", domain: "n8n.example.com" }]));

    expect(html).toContain("|n8n.example.com|");
    expect(html).toContain("|ConnectionPanel.modeDomain · 5678/tcp|");
  });

  it("does the same for a course template URL, which only has an explicit mode", () => {
    const html = text(inbound([{ port: 5678, protocol: "tcp", mode: "domain", domain: "n8nai-xxxx.example.com" }]));

    expect(html).toContain("|ConnectionPanel.modeDomain · 5678/tcp|");
  });

  it("keeps the port on the first line for port forwarding and firewall-only rules", () => {
    const html = text(inbound([
      { port: 22, protocol: "tcp", external_port: 30022 },
      { port: 5678, protocol: "tcp", mode: "port_forward" },
      { port: 9999, protocol: "udp" },
      { port: 0, protocol: "icmp" },
    ]));

    expect(html).toContain("|30022 → 22|ConnectionPanel.modePortForward · tcp|");
    expect(html).toContain("|5678/tcp|ConnectionPanel.modePortForward · tcp|");
    expect(html).toContain("|9999/udp|ConnectionPanel.modeFirewallOnly · udp|");
    expect(html).toContain("|ICMP|ConnectionPanel.modeFirewallOnly · icmp|");
  });
});

describe("ConnectionDetailPanel search indexing switch", () => {
  const inbound = {
    source_vmid: null,
    target_vmid: 150,
    direction: "one_way",
    ports: [
      { port: 80, protocol: "tcp", domain: "me.example.com", allow_indexing: false },
      { port: 22, protocol: "tcp", external_port: 30022 },
    ],
  };
  const panel = (props) => renderToStaticMarkup(
    <ConnectionDetailPanel
      edge={inbound}
      resolveName={(vmid) => `vm-${vmid}`}
      onClose={() => {}}
      {...props}
    />,
  );

  it("shows one switch, on the URL only, reflecting the current setting", () => {
    const html = panel({ onToggleIndexing: () => {} });

    expect(html.match(/role="switch"/g)).toHaveLength(1);
    expect(html).toContain('aria-checked="false"');
    expect(html).toContain("ConnectionPanel.allowIndexing");
  });

  it("is hidden for people who cannot manage the machine and on course templates", () => {
    expect(panel({})).not.toContain('role="switch"');
    expect(panel({ onToggleIndexing: () => {}, allowOpen: false })).not.toContain('role="switch"');
  });

  it("is disabled while a change is being saved", () => {
    const html = panel({ onToggleIndexing: () => {}, indexingBusy: true });
    expect(html).toMatch(/role="switch"[^>]*disabled=""/);
  });
});
