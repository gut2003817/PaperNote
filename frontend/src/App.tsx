import { useEffect, useState } from "react";
import { HealthLight } from "./HealthLight";
import { PaperList } from "./pages/PaperList";
import { PaperView } from "./pages/PaperView";

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
  const hash = useHash();
  const m = hash.match(/^#\/paper\/([a-z0-9-]+)$/);
  return (
    <>
      <header className="app-header">
        <a href="#/">Paper Notes</a>
        <HealthLight />
      </header>
      {m ? <PaperView slug={m[1]} /> : <PaperList />}
    </>
  );
}
