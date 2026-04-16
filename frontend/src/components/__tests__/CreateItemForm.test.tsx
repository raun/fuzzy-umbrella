import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CreateItemForm } from "../CreateItemForm";
import type { ItemResponse } from "../../api/items";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeItemResponse(overrides: Partial<ItemResponse> = {}): ItemResponse {
  return {
    id: "new-id-123",
    name: "Widget",
    description: null,
    created_at: "2026-04-15T00:00:00Z",
    ...overrides,
  };
}

function mockFetchSuccess(responseData: ItemResponse) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      statusText: "Created",
      json: async () => responseData,
    } as Response)
  );
}

function mockFetchFailure(status: number, statusText: string) {
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

describe("CreateItemForm", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  describe("initial render", () => {
    it("renders a Name input", () => {
      render(<CreateItemForm onCreated={vi.fn()} />);
      expect(screen.getByLabelText(/name/i)).toBeInTheDocument();
    });

    it("renders a Description input", () => {
      render(<CreateItemForm onCreated={vi.fn()} />);
      expect(screen.getByLabelText(/description/i)).toBeInTheDocument();
    });

    it("renders a submit button labelled 'Create Item'", () => {
      render(<CreateItemForm onCreated={vi.fn()} />);
      expect(screen.getByRole("button", { name: /create item/i })).toBeInTheDocument();
    });

    it("submit button is enabled initially", () => {
      render(<CreateItemForm onCreated={vi.fn()} />);
      expect(screen.getByRole("button", { name: /create item/i })).not.toBeDisabled();
    });
  });

  describe("successful submission", () => {
    it("calls fetch with correct POST arguments", async () => {
      const response = makeItemResponse({ name: "Widget" });
      mockFetchSuccess(response);

      render(<CreateItemForm onCreated={vi.fn()} />);
      await userEvent.type(screen.getByLabelText(/name/i), "Widget");
      await userEvent.click(screen.getByRole("button", { name: /create item/i }));

      await waitFor(() => {
        expect(vi.mocked(fetch)).toHaveBeenCalledOnce();
      });

      const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
      expect(url).toContain("/api/items");
      expect(init.method).toBe("POST");
      const body = JSON.parse(init.body as string) as Record<string, unknown>;
      expect(body.name).toBe("Widget");
    });

    it("fires onCreated callback after successful submission", async () => {
      const response = makeItemResponse({ name: "Widget" });
      mockFetchSuccess(response);
      const onCreated = vi.fn();

      render(<CreateItemForm onCreated={onCreated} />);
      await userEvent.type(screen.getByLabelText(/name/i), "Widget");
      await userEvent.click(screen.getByRole("button", { name: /create item/i }));

      await waitFor(() => {
        expect(onCreated).toHaveBeenCalledOnce();
      });
    });

    it("clears the name field after successful submission", async () => {
      mockFetchSuccess(makeItemResponse());
      render(<CreateItemForm onCreated={vi.fn()} />);
      const nameInput = screen.getByLabelText(/name/i) as HTMLInputElement;

      await userEvent.type(nameInput, "Widget");
      await userEvent.click(screen.getByRole("button", { name: /create item/i }));

      await waitFor(() => {
        expect(nameInput.value).toBe("");
      });
    });

    it("sends description as null when description field is empty", async () => {
      const response = makeItemResponse({ name: "NoDesc", description: null });
      mockFetchSuccess(response);

      render(<CreateItemForm onCreated={vi.fn()} />);
      await userEvent.type(screen.getByLabelText(/name/i), "NoDesc");
      // leave description blank
      await userEvent.click(screen.getByRole("button", { name: /create item/i }));

      await waitFor(() => {
        expect(vi.mocked(fetch)).toHaveBeenCalledOnce();
      });

      const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
      const body = JSON.parse(init.body as string) as Record<string, unknown>;
      expect(body.description).toBeNull();
    });

    it("sends description when description field is filled in", async () => {
      const response = makeItemResponse({ name: "WithDesc", description: "Some desc" });
      mockFetchSuccess(response);

      render(<CreateItemForm onCreated={vi.fn()} />);
      await userEvent.type(screen.getByLabelText(/name/i), "WithDesc");
      await userEvent.type(screen.getByLabelText(/description/i), "Some desc");
      await userEvent.click(screen.getByRole("button", { name: /create item/i }));

      await waitFor(() => {
        expect(vi.mocked(fetch)).toHaveBeenCalledOnce();
      });

      const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
      const body = JSON.parse(init.body as string) as Record<string, unknown>;
      expect(body.description).toBe("Some desc");
    });
  });

  describe("failed submission (non-ok response)", () => {
    it("renders an error alert when the request fails", async () => {
      mockFetchFailure(500, "Internal Server Error");

      render(<CreateItemForm onCreated={vi.fn()} />);
      await userEvent.type(screen.getByLabelText(/name/i), "Widget");
      await userEvent.click(screen.getByRole("button", { name: /create item/i }));

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });
    });

    it("error message reflects the HTTP status", async () => {
      mockFetchFailure(422, "Unprocessable Entity");

      render(<CreateItemForm onCreated={vi.fn()} />);
      await userEvent.type(screen.getByLabelText(/name/i), "Widget");
      await userEvent.click(screen.getByRole("button", { name: /create item/i }));

      await waitFor(() => {
        const alert = screen.getByRole("alert");
        expect(alert.textContent).toMatch(/422/);
      });
    });

    it("does NOT call onCreated when the request fails", async () => {
      mockFetchFailure(500, "Internal Server Error");
      const onCreated = vi.fn();

      render(<CreateItemForm onCreated={onCreated} />);
      await userEvent.type(screen.getByLabelText(/name/i), "Widget");
      await userEvent.click(screen.getByRole("button", { name: /create item/i }));

      await waitFor(() => screen.getByRole("alert"));
      expect(onCreated).not.toHaveBeenCalled();
    });
  });

  describe("failed submission (network error)", () => {
    it("renders an error alert when fetch rejects", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockRejectedValue(new Error("Network failure"))
      );

      render(<CreateItemForm onCreated={vi.fn()} />);
      await userEvent.type(screen.getByLabelText(/name/i), "Widget");
      await userEvent.click(screen.getByRole("button", { name: /create item/i }));

      await waitFor(() => {
        const alert = screen.getByRole("alert");
        expect(alert.textContent).toMatch(/Network failure/);
      });
    });
  });

  describe("submitting state", () => {
    it("disables the button while submitting", async () => {
      // Make fetch hang so we can observe the submitting state
      let resolveFetch!: (value: Response) => void;
      const hangingPromise = new Promise<Response>((resolve) => {
        resolveFetch = resolve;
      });
      vi.stubGlobal("fetch", vi.fn().mockReturnValue(hangingPromise));

      render(<CreateItemForm onCreated={vi.fn()} />);
      await userEvent.type(screen.getByLabelText(/name/i), "Widget");
      await userEvent.click(screen.getByRole("button", { name: /create item/i }));

      // Button should now be disabled
      expect(screen.getByRole("button", { name: /creating/i })).toBeDisabled();

      // Resolve the hanging fetch so the component settles
      resolveFetch({
        ok: true,
        status: 201,
        statusText: "Created",
        json: async () => makeItemResponse(),
      } as Response);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /create item/i })).not.toBeDisabled();
      });
    });
  });
});
