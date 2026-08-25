/** @vitest-environment jsdom */

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Toaster, toast } from "./sonner";

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
  vi.stubGlobal(
    "ResizeObserver",
    class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  act(() => {
    toast.dismiss();
  });
  cleanup();
});

function toastElement(message: string) {
  return screen.getByText(message).closest<HTMLElement>("[data-sonner-toast]");
}

describe("Toaster", () => {
  it("renders page notifications at the top center with semantic design tokens", async () => {
    render(<Toaster />);

    act(() => {
      toast.success("保存完成");
      toast.warning("部分项目需要检查");
      toast.error("保存失败");
    });

    await screen.findByText("保存完成");
    const success = toastElement("保存完成");
    const warning = toastElement("部分项目需要检查");
    const error = toastElement("保存失败");
    const lane = success?.closest<HTMLElement>("[data-sonner-toaster]");

    expect(success?.getAttribute("data-type")).toBe("success");
    expect(warning?.getAttribute("data-type")).toBe("warning");
    expect(error?.getAttribute("data-type")).toBe("error");
    expect(success?.getAttribute("data-rich-colors")).toBe("true");
    expect(lane?.getAttribute("data-y-position")).toBe("top");
    expect(lane?.getAttribute("data-x-position")).toBe("center");
    expect(lane?.style.getPropertyValue("--success-bg")).toBe(
      "var(--status-success-bg)",
    );
    expect(lane?.style.getPropertyValue("--warning-text")).toBe(
      "var(--warning)",
    );
    expect(lane?.style.getPropertyValue("--error-border")).toBe(
      "var(--status-danger-border)",
    );
  });

  it("keeps all notifications in the same centered lane", async () => {
    const { container } = render(<Toaster />);

    act(() => {
      toast.success("页面操作完成");
      toast.error("另一项操作失败");
    });

    await screen.findByText("另一项操作失败");
    const pageLane = toastElement("页面操作完成")?.closest<HTMLElement>(
      "[data-sonner-toaster]",
    );
    const actionLane = toastElement("另一项操作失败")?.closest<HTMLElement>(
      "[data-sonner-toaster]",
    );

    expect(container.querySelectorAll("section")).toHaveLength(1);
    expect(pageLane?.getAttribute("data-x-position")).toBe("center");
    expect(actionLane?.getAttribute("data-y-position")).toBe("top");
    expect(actionLane?.getAttribute("data-x-position")).toBe("center");
    await waitFor(() =>
      expect(
        toastElement("另一项操作失败")?.querySelector(
          '[data-close-button][aria-label="关闭通知"]',
        ),
      ).not.toBeNull(),
    );
  });
});
