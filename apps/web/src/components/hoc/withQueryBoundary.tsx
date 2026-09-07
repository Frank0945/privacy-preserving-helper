import type { ComponentType, FC } from "react";
import { Suspense } from "react";
import { Spinner } from "@/components/atoms/spinner";
import { QueryErrorResetBoundary } from "@tanstack/react-query";
import { OctagonXIcon } from "lucide-react";
import { ErrorBoundary } from "react-error-boundary";

/**
 * Wraps a component with `ErrorBoundary` and `Suspense` to handle query errors and loading status.
 */
const withQueryBoundary = <T extends object>(Component: ComponentType<T>) => {
  const QueryBoundaryHOC: FC<T> = (props) => {
    return (
      <QueryErrorResetBoundary>
        {({ reset }) => (
          <ErrorBoundary
            onReset={reset}
            fallbackRender={({ error }) => (
              <div className="text-destructive my-8 flex flex-row items-center gap-2">
                <OctagonXIcon className="size-6" />
                Error: {error.message}
              </div>
            )}
          >
            <Suspense
              fallback={
                <div className="my-8 flex flex-col items-center gap-2">
                  <Spinner className="size-8" />
                  <span>Loading</span>
                </div>
              }
            >
              <Component {...props} />
            </Suspense>
          </ErrorBoundary>
        )}
      </QueryErrorResetBoundary>
    );
  };
  return QueryBoundaryHOC;
};

export default withQueryBoundary;
