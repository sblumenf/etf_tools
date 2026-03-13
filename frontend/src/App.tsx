import { Component, type ReactNode } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Home } from "./pages/Home";
import { XRay } from "./pages/XRay";
import "./index.css";

class ErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean; message: string }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, message: error.message };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center min-h-screen gap-4 p-8">
          <p className="text-destructive font-semibold text-lg">Something went wrong</p>
          {this.state.message && (
            <p className="text-sm text-muted-foreground">{this.state.message}</p>
          )}
          <a href="/" className="text-sm text-muted-foreground underline">
            Back to search
          </a>
        </div>
      );
    }
    return this.props.children;
  }
}

function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/xray/:ticker" element={<XRay />} />
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  );
}

export default App;
