import { useEffect, useState } from "react";
import { deleteItem, listItems, type ItemResponse } from "../api/items";

interface Props {
  /** Increment to trigger a refresh of the item list. */
  refreshKey: number;
}

export function ItemList({ refreshKey }: Props) {
  const [items, setItems] = useState<ItemResponse[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listItems()
      .then((data) => {
        if (!cancelled) {
          setItems(data);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Unknown error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  async function handleDelete(id: string) {
    try {
      await deleteItem(id);
      setItems((prev) => prev.filter((item) => item.id !== id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to delete item");
    }
  }

  if (error) {
    return <p role="alert">Error: {error}</p>;
  }

  if (items.length === 0) {
    return <p>No items</p>;
  }

  return (
    <ul>
      {items.map((item) => (
        <li key={item.id}>
          <strong>{item.name}</strong>
          {item.description ? ` — ${item.description}` : ""}
          <button onClick={() => void handleDelete(item.id)} style={{ marginLeft: "0.5rem" }}>
            Delete
          </button>
        </li>
      ))}
    </ul>
  );
}
