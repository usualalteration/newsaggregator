import { Toaster as Sonner } from "@/components/ui/sonner";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HashRouter, Routes, Route } from "react-router-dom";
import News from "./pages/News";
import Sources from "./pages/Search";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <Sonner />
    <HashRouter>
      <Routes>
        <Route path="/" element={<News />} />
          <Route path="/search" element={<Sources />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </HashRouter>
  </QueryClientProvider>
);

export default App;