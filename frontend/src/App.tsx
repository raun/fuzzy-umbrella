import { useState } from "react";
import { CreateItemForm } from "./components/CreateItemForm";
import { ItemList } from "./components/ItemList";

export default function App() {
  const [refreshKey, setRefreshKey] = useState(0);

  function handleCreated() {
    setRefreshKey((k) => k + 1);
  }

  return (
    <main>
      <h1>Items</h1>
      <CreateItemForm onCreated={handleCreated} />
      <ItemList refreshKey={refreshKey} />
    </main>
  );
}
