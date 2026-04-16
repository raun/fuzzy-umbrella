import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ItemList } from "../ItemList";
import type { ItemResponse } from "../../api/items";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeItem(overrides: Partial<ItemResponse> = {}): ItemResponse {
  return {
    id: "test-id-1",
    name: "Test Widget",
    description: null,
    created_at: "2026-04-15T00:00:00Z",
    ...overrides,
  };
}

function mockFetchSuccess(data: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      statusText: status === 200 ? "OK" : "Error",
      json: async () => data,
    } as Response)
  );
}

function mockFetchFailure(status: number, statusText = "Internal Server Error") {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status,
      statusText,
      json: async () => ({}),
    } as Response)
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ItemList", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  describe("when the server returns an empty list", () => {
    beforeEach(() => {
      mockFetchSuccess([]);
    });

    it('renders "No items" text', async () => {
      render(<ItemList refreshKey={0} />);
      await waitFor(() => {
        expect(screen.getByText("No items")).toBeInTheDocument();
      });
    });

    it("does not render a list element", async () => {
      render(<ItemList refreshKey={0} />);
      await waitFor(() => screen.getByText("No items"));
      expect(screen.queryByRole("list")).not.toBeInTheDocument();
    });
  });

  describe("when the server returns a list of items", () => {
    const items: ItemResponse[] = [
      makeItem({ id: "id-1", name: "Alpha", description: "First item" }),
      makeItem({ id: "id-2", name: "Beta", description: null }),
    ];

    beforeEach(() => {
      mockFetchSuccess(items);
    });

    it("renders an item name for each item", async () => {
      render(<ItemList refreshKey={0} />);
      await waitFor(() => {
        expect(screen.getByText("Alpha")).toBeInTheDocument();
        expect(screen.getByText("Beta")).toBeInTheDocument();
      });
    });

    it("renders the description when it is set", async () => {
      render(<ItemList refreshKey={0} />);
      await waitFor(() => {
        expect(screen.getByText(/First item/)).toBeInTheDocument();
      });
    });

    it("renders a Delete button for each item", async () => {
      render(<ItemList refreshKey={0} />);
      await waitFor(() => {
        const buttons = screen.getAllByRole("button", { name: /delete/i });
        expect(buttons).toHaveLength(2);
      });
    });

    it("does NOT render the 'No items' message", async () => {
      render(<ItemList refreshKey={0} />);
      await waitFor(() => screen.getAllByRole("listitem"));
      expect(screen.queryByText("No items")).not.toBeInTheDocument();
    });
  });

  describe("when fetch fails (non-ok response)", () => {
    beforeEach(() => {
      mockFetchFailure(500, "Internal Server Error");
    });

    it("renders an error alert", async () => {
      render(<ItemList refreshKey={0} />);
      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });
    });

    it("error message contains the HTTP status information", async () => {
      render(<ItemList refreshKey={0} />);
      await waitFor(() => {
        const alert = screen.getByRole("alert");
        expect(alert.textContent).toMatch(/500/);
      });
    });
  });

  describe("when fetch rejects (network error)", () => {
    beforeEach(() => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockRejectedValue(new Error("Network failure"))
      );
    });

    it("renders an error alert with the rejection message", async () => {
      render(<ItemList refreshKey={0} />);
      await waitFor(() => {
        const alert = screen.getByRole("alert");
        expect(alert.textContent).toMatch(/Network failure/);
      });
    });
  });

  describe("delete behaviour", () => {
    const items: ItemResponse[] = [
      makeItem({ id: "id-del", name: "DeleteMe" }),
      makeItem({ id: "id-keep", name: "KeepMe" }),
    ];

    it("removes item from list after delete button is clicked", async () => {
      // First call = listItems, subsequent DELETE call = ok 204
      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => items,
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          status: 204,
          json: async () => null,
        } as Response);
      vi.stubGlobal("fetch", fetchMock);

      render(<ItemList refreshKey={0} />);
      await waitFor(() => screen.getByText("DeleteMe"));

      const deleteButtons = screen.getAllByRole("button", { name: /delete/i });
      await userEvent.click(deleteButtons[0]);

      await waitFor(() => {
        expect(screen.queryByText("DeleteMe")).not.toBeInTheDocument();
      });
      expect(screen.getByText("KeepMe")).toBeInTheDocument();
    });
  });

  describe("refreshKey prop", () => {
    it("re-fetches items when refreshKey changes", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [] as ItemResponse[],
      } as Response);
      vi.stubGlobal("fetch", fetchMock);

      const { rerender } = render(<ItemList refreshKey={0} />);
      await waitFor(() => screen.getByText("No items"));

      rerender(<ItemList refreshKey={1} />);
      await waitFor(() => {
        // fetch should have been called at least twice
        expect(fetchMock).toHaveBeenCalledTimes(2);
      });
    });
  });
});
