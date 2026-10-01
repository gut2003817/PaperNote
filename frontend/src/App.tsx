import { useEffect, useState } from "react";
import { HealthLight } from "./HealthLight";
import { PaperList } from "./pages/PaperList";

function useHash() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const onChange = () => setHash(location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

export default function App() {
  useHash();
  return (
    <>
      <header className="app-header">
        <a href="#/">Paper Notes</a>
        <HealthLight />
      </header>
      <PaperList />
    </>
  );
}
