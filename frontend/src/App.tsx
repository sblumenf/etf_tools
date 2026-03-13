import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Home } from "./pages/Home";
import { XRay } from "./pages/XRay";
import "./index.css";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/xray/:ticker" element={<XRay />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
