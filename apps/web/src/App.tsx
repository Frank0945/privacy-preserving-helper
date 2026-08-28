import { ThemeProvider } from "@/layouts/siteHeader/providers/themeProvider";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import routes from "~react-pages";
import { BrowserRouter, useRoutes } from "react-router-dom";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: Infinity,
      gcTime: 1000 * 60 * 60, // 1 hour
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      refetchOnMount: false,
    },
  },
});

const App = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ThemeProvider storageKey="vite-ui-theme">
          <CurrentRoute />
        </ThemeProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

const CurrentRoute = () => useRoutes(routes);

export default App;
