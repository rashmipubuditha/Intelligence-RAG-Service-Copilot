/**
 * Router + providers.
 *
 * Query defaults are chosen for a tool whose data changes on *our* actions rather than on a
 * server timer: a short stale window, no refetch on window focus (it would re-run document
 * lists while the user is reading one), and no retry on 4xx because a 404 or a 422 will not
 * fix itself.
 */

import { Component, type ErrorInfo, type ReactNode, Suspense, lazy } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "../lib/api";
import { ErrorState, SkeletonText } from "../components/ui";
import { Layout } from "./Layout";

const Dashboard = lazy(() => import("../pages/Dashboard"));
const Chat = lazy(() => import("../pages/Chat"));
const Documents = lazy(() => import("../pages/Documents"));
const DocumentDetail = lazy(() => import("../pages/DocumentDetail"));
const Evaluation = lazy(() => import("../pages/Evaluation"));
const Settings = lazy(() => import("../pages/Settings"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (error instanceof ApiError && !error.isRetryable) return false;
        return failureCount < 2;
      },
    },
    mutations: { retry: false },
  },
});

/** Catches render-time crashes so a component bug degrades one route, not the whole app. */
class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled render error", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <ErrorState
          title="This view failed to render"
          message={this.state.error.message}
          onRetry={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}

function RouteFallback() {
  return (
    <div className="p-6">
      <SkeletonText lines={5} />
    </div>
  );
}

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: "chat", element: <Chat /> },
      { path: "chat/:conversationId", element: <Chat /> },
      { path: "documents", element: <Documents /> },
      { path: "documents/:documentId", element: <DocumentDetail /> },
      { path: "evaluation", element: <Evaluation /> },
      { path: "settings", element: <Settings /> },
      {
        path: "*",
        element: (
          <ErrorState
            title="Page not found"
            message="That route does not exist. Use the navigation to continue."
          />
        ),
      },
    ],
  },
]);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <Suspense fallback={<RouteFallback />}>
          <RouterProvider router={router} />
        </Suspense>
      </ErrorBoundary>
    </QueryClientProvider>
  );
}
