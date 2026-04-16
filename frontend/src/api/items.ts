/** Typed fetch wrappers for the items API. */

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export interface ItemCreate {
  name: string;
  description?: string | null;
}

export interface ItemResponse {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}

export async function listItems(): Promise<ItemResponse[]> {
  const res = await fetch(`${BASE}/api/items`);
  if (!res.ok) {
    throw new Error(`Failed to fetch items: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<ItemResponse[]>;
}

export async function createItem(data: ItemCreate): Promise<ItemResponse> {
  const res = await fetch(`${BASE}/api/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    throw new Error(`Failed to create item: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<ItemResponse>;
}

export async function deleteItem(id: string): Promise<void> {
  const res = await fetch(`${BASE}/api/items/${id}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`Failed to delete item: ${res.status} ${res.statusText}`);
  }
}
